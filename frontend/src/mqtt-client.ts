import mqtt, { type MqttClient, type IPublishPacket } from 'mqtt'
import type { FontInfo, MQTTFrontendConfig, PrinterInfo, PrinterStatusMessage, PrintStats } from './types'

interface DiscoveredPrinter {
  printer: PrinterInfo
  printerName: string
  online: boolean
  busy: boolean
  lastError: string | null
  lastSeen: number
}

interface PrintCommandPayload {
  job_id: string
  sent_at: string
  printer_name: string
  payload_type: 'image' | 'zpl'
  payload_encoding: 'data_url' | 'utf8' | 'base64_png' | 'base64_chunk' | 'utf8_chunk' | 'base64_utf8' | 'base64_utf8_chunk'
  payload: string
  chunk_index?: number
  chunks_total?: number
}

let client: MqttClient | null = null
let mqttConfig: MQTTFrontendConfig | null = null
let connected = false
let lastConnectionError: string | null = null

function normalizeBrokerURL(raw: string): string {
  const trimmed = raw.trim()
  if (!trimmed) return trimmed

  // Browser MQTT transport is websocket-based; accept mqtt/mqtts aliases.
  const wsCompatible = trimmed
    .replace(/^mqtt:\/\//i, 'ws://')
    .replace(/^mqtts:\/\//i, 'wss://')

  const url = new URL(wsCompatible)

  // HiveMQ Cloud websocket endpoint expects /mqtt.
  if (
    url.hostname.endsWith('.hivemq.cloud')
    && (url.pathname === '' || url.pathname === '/')
  ) {
    url.pathname = '/mqtt'
  }

  return url.toString()
}

const discovered = new Map<string, DiscoveredPrinter>()
const statusListeners = new Set<() => void>()

// Retained topic for fonts uploaded via the Fonts tab, so a font one
// visitor uploads becomes available to every browser instead of only the
// one that saved it locally. Unlike the ESP32 status/command topics, this
// is browser-to-browser only -- the firmware never subscribes here -- so
// the firmware's 65535-byte MQTT buffer ceiling doesn't apply; fonts go out
// as a single message regardless of size.
const SHARED_FONTS_TOPIC = '/_stikka/fonts/'

// Retained topic for print statistics. Same rationale as SHARED_FONTS_TOPIC:
// the ESP32 bridge only relays raw bytes and has no notion of "cat" vs
// "upload" vs "no image", so counts are tallied client-side and shared here
// so every browser sees the same global totals instead of each tracking its
// own (previously fetchStats() was a stub that always returned zeros).
const SHARED_STATS_TOPIC = '/_stikka/stats/'

// Firmware falls back to this name (main.cpp) when a device hasn't been
// given a unique printer name yet. It's not unique across devices, so
// treating it as a real discoverable printer risks sending a job to the
// wrong (or multiple) unconfigured units. Ignore status from it entirely.
const DEFAULT_PRINTER_NAME = 'stikka-esp32'

// A node that loses power or Wi-Fi never gets to publish an "offline"
// status -- it just stops. Without an active timeout it would linger in the
// discovered-printers list forever. Forget it after this long without any
// status message (retained or live).
const NODE_TIMEOUT_MS = 5 * 60 * 1000
const NODE_TIMEOUT_CHECK_INTERVAL_MS = 30 * 1000
let pruneIntervalId: number | null = null

let remoteFonts: FontInfo[] | null = null
const sharedFontsListeners = new Set<() => void>()

function notifySharedFontsListeners(): void {
  for (const listener of sharedFontsListeners) listener()
}

let remoteStats: PrintStats | null = null
const sharedStatsListeners = new Set<() => void>()

function notifySharedStatsListeners(): void {
  for (const listener of sharedStatsListeners) listener()
}

function normalizeStats(raw: Partial<PrintStats> | null | undefined): PrintStats {
  return {
    printed_total: raw?.printed_total ?? 0,
    printed_cats: raw?.printed_cats ?? 0,
    printed_dogs: raw?.printed_dogs ?? 0,
    printed_dinos: raw?.printed_dinos ?? 0,
    printed_uploaded_images: raw?.printed_uploaded_images ?? 0,
    printed_webcam_images: raw?.printed_webcam_images ?? 0,
    printed_without_image: raw?.printed_without_image ?? 0,
  }
}

function normalizeLabel(raw: PrinterStatusMessage): PrinterInfo['label'] {
  const src = raw.capabilities?.label ?? raw.label ?? {}
  return {
    width: src.width ?? 80,
    length: src.length ?? 80,
    isRound: src.isRound ?? false,
    verticalOffset: src.verticalOffset ?? 0,
    cut: src.cut ?? false,
  }
}

function statusToPrinter(name: string, status: PrinterStatusMessage): PrinterInfo {
  const kind = status.capabilities?.type ?? status.type ?? 'zpl'
  const dpi = status.capabilities?.dpi ?? status.dpi ?? 203
  const label = normalizeLabel(status)
  return {
    index: 0,
    name,
    serial: status.serial ?? '',
    type: kind,
    dpi,
    label,
    zplCompressionSupported: status.capabilities?.zplCompression ?? false,
  }
}

function notifyStatusListeners(): void {
  for (const listener of statusListeners) listener()
}

function randomClientId(prefix: string): string {
  const suffix = Math.random().toString(36).slice(2, 10)
  return `${prefix}-${suffix}`
}

function nowIso(): string {
  return new Date().toISOString()
}

function makeJobId(): string {
  const rand = Math.random().toString(36).slice(2, 12)
  return `job-${Date.now()}-${rand}`
}

// Keep this well under what the ESP32 needs to hold as one contiguous
// allocation. It's not just the MQTT buffer ceiling (PubSubClient negotiates
// up to 65535 bytes, since bufferSize is a uint16_t) -- the firmware also
// copies the payload into a String (onMqttMessage's `msg`) before parsing
// it, and on a heap already carrying that MQTT buffer plus WiFi/TLS
// overhead, a single ~40KB contiguous String allocation can fail while a
// much smaller one succeeds. Small chunks keep every individual allocation
// on the ESP32 side small regardless of the total image size.
const IMAGE_CHUNK_SIZE = 8000
const ZPL_CHUNK_SIZE = 8000

function chunkStringSafely(text: string, maxChunkSize: number): string[] {
  const chunks: string[] = []
  let start = 0
  while (start < text.length) {
    let end = Math.min(start + maxChunkSize, text.length)
    // Don't split a UTF-16 surrogate pair across a chunk boundary.
    if (end < text.length && text.charCodeAt(end - 1) >= 0xd800 && text.charCodeAt(end - 1) <= 0xdbff) {
      end -= 1
    }
    chunks.push(text.slice(start, end))
    start = end
  }
  return chunks
}

function statusTopicForPrinter(printerName: string): string {
  return `/${printerName}/status/`
}

function commandTopicForPrinter(printerName: string): string {
  return `/${printerName}/command/`
}

function setDiscoveredPrinter(name: string, message: PrinterStatusMessage, retained: boolean): void {
  const prior = discovered.get(name)
  const printer = statusToPrinter(name, message)
  const entry: DiscoveredPrinter = {
    printer: {
      ...printer,
      index: prior?.printer.index ?? discovered.size,
    },
    printerName: name,
    online: message.online ?? true,
    busy: message.busy ?? false,
    lastError: message.last_error ?? null,
    // Every reconnect re-subscribes to the status wildcard, and the broker
    // replays each printer's retained message on subscribe -- including one
    // from a node that's been dead for hours. Treating that replay as "seen
    // now" would reset the prune clock forever on a flaky connection, so
    // only a live (non-retained) publish bumps lastSeen; a retained replay
    // keeps whatever lastSeen this printer already had (or "now", the first
    // time we see it, so a newly-discovered node isn't pruned immediately).
    lastSeen: retained && prior ? prior.lastSeen : Date.now(),
  }
  discovered.set(name, entry)
  notifyStatusListeners()
}

function pruneStaleDiscoveredPrinters(): void {
  const now = Date.now()
  let removed = false
  for (const [name, entry] of discovered) {
    if (now - entry.lastSeen > NODE_TIMEOUT_MS) {
      discovered.delete(name)
      removed = true
    }
  }
  if (removed) notifyStatusListeners()
}

function subscribeStatusTopics(cfg: MQTTFrontendConfig): void {
  if (!client) return
  const wildcard = '/+/status/#'
  client.subscribe(wildcard, { qos: 1 }, err => {
    if (err) console.error('MQTT status subscribe failed:', err)
  })
  client.subscribe(SHARED_FONTS_TOPIC, { qos: 1 }, err => {
    if (err) console.error('MQTT shared fonts subscribe failed:', err)
  })
  client.subscribe(SHARED_STATS_TOPIC, { qos: 1 }, err => {
    if (err) console.error('MQTT shared stats subscribe failed:', err)
  })
}

function onMessage(topic: string, payload: Uint8Array, packet: IPublishPacket): void {
  if (topic === SHARED_FONTS_TOPIC) {
    try {
      const text = new TextDecoder().decode(payload)
      remoteFonts = text ? (JSON.parse(text) as FontInfo[]) : []
    } catch (err) {
      console.warn('Ignoring malformed shared fonts payload:', err)
    }
    notifySharedFontsListeners()
    return
  }

  if (topic === SHARED_STATS_TOPIC) {
    try {
      const text = new TextDecoder().decode(payload)
      remoteStats = normalizeStats(text ? (JSON.parse(text) as Partial<PrintStats>) : null)
    } catch (err) {
      console.warn('Ignoring malformed shared stats payload:', err)
    }
    notifySharedStatsListeners()
    return
  }

  if (!topic.startsWith('/')) return
  const parts = topic.split('/').filter(Boolean)
  if (parts.length < 2) return
  if (parts[1] !== 'status') return
  const printerName = parts[0]
  if (!printerName) return

  try {
    const text = new TextDecoder().decode(payload)
    const json = JSON.parse(text) as PrinterStatusMessage
    // Per-job status updates (publishJobStatus() in main.cpp) share this
    // topic with full status snapshots but carry no label/capabilities --
    // treating them as a full snapshot would blow away the real printer
    // info with normalizeLabel()'s 80x80mm/etc. defaults on every print.
    if (json.phase === undefined) return
    const resolvedName = json.printer_name ?? json.name ?? printerName
    if (resolvedName.toLowerCase() === DEFAULT_PRINTER_NAME) return
    setDiscoveredPrinter(resolvedName, json, packet.retain)
  } catch (err) {
    console.warn('Ignoring malformed printer status payload:', err)
  }
}

export async function initMQTTTransport(cfg: MQTTFrontendConfig): Promise<void> {
  if (client) {
    client.end(true)
    client = null
  }
  connected = false
  lastConnectionError = null
  discovered.clear()
  remoteFonts = null
  remoteStats = null
  notifyStatusListeners()
  notifySharedFontsListeners()
  notifySharedStatsListeners()

  if (pruneIntervalId !== null) {
    window.clearInterval(pruneIntervalId)
  }
  pruneIntervalId = window.setInterval(pruneStaleDiscoveredPrinters, NODE_TIMEOUT_CHECK_INTERVAL_MS)

  const connectURL = normalizeBrokerURL(cfg.brokerURL)
  mqttConfig = { ...cfg, brokerURL: connectURL }

  const clientIdPrefix = cfg.clientIdPrefix ?? 'stikka-web'
  const connectTimeoutMs = 10000
  client = mqtt.connect(connectURL, {
    clientId: randomClientId(clientIdPrefix),
    username: cfg.username,
    password: cfg.password,
    reconnectPeriod: 3000,
    keepalive: 30,
    connectTimeout: connectTimeoutMs,
    clean: true,
  })

  await new Promise<void>((resolve) => {
    if (!client) {
      lastConnectionError = 'MQTT client was not initialized'
      return
    }

    const firstConnectTimeoutMs = connectTimeoutMs + 2000
    let settled = false
    let timer: number | null = window.setTimeout(() => {
      if (settled) return
      settled = true
      cleanup()
      lastConnectionError = `MQTT connect timeout after ${firstConnectTimeoutMs}ms`
      console.warn(lastConnectionError)
      resolve()
    }, firstConnectTimeoutMs)

    const cleanup = (): void => {
      if (timer !== null) {
        clearTimeout(timer)
        timer = null
      }
      client?.off('connect', onConnect)
      client?.off('error', onError)
    }

    const onConnect = (): void => {
      if (settled) return
      settled = true
      cleanup()
      connected = true
      lastConnectionError = null
      subscribeStatusTopics(cfg)
      notifyStatusListeners()
      resolve()
    }

    const onError = (err: Error): void => {
      if (settled) {
        lastConnectionError = err.message
        connected = false
        notifyStatusListeners()
        return
      }
      settled = true
      cleanup()
      lastConnectionError = err.message
      connected = false
      notifyStatusListeners()
      resolve()
    }

    client.on('connect', onConnect)
    client.on('error', onError)
  })

  client.on('connect', () => {
    connected = true
    lastConnectionError = null
    subscribeStatusTopics(cfg)
    notifyStatusListeners()
  })

  client.on('close', () => {
    connected = false
    notifyStatusListeners()
  })

  client.on('error', (err) => {
    connected = false
    lastConnectionError = err.message
    notifyStatusListeners()
  })

  client.on('message', (topic, payload, packet) => onMessage(topic, payload, packet))
}

export function onMQTTStatusChanged(listener: () => void): () => void {
  statusListeners.add(listener)
  return () => statusListeners.delete(listener)
}

export function getDiscoveredPrinters(): PrinterInfo[] {
  return Array.from(discovered.values()).map((entry, idx) => ({
    ...entry.printer,
    index: idx,
  }))
}

export function getDiscoveredPrinterMeta(printerName: string): { online: boolean; busy: boolean; lastError: string | null } | null {
  const entry = discovered.get(printerName)
  if (!entry) return null
  return {
    online: entry.online,
    busy: entry.busy,
    lastError: entry.lastError,
  }
}

export function isMQTTConnected(): boolean {
  return connected
}

export function getMQTTLastError(): string | null {
  return lastConnectionError
}

function ensureConnected(): void {
  if (!client || !connected || !mqttConfig) {
    throw new Error('MQTT is not connected')
  }
}

function publishCommand(printerName: string, payload: PrintCommandPayload): Promise<void> {
  ensureConnected()
  const topic = commandTopicForPrinter(printerName)
  return new Promise<void>((resolve, reject) => {
    client?.publish(topic, JSON.stringify(payload), { qos: 1 }, err => {
      if (err) reject(err)
      else resolve()
    })
  })
}

export async function publishImageCommand(printerName: string, imageDataURL: string): Promise<void> {
  const comma = imageDataURL.indexOf(',')
  if (comma > 0 && imageDataURL.slice(0, comma).includes('base64')) {
    const base64 = imageDataURL.slice(comma + 1)
    await publishBase64PNGCommand(printerName, base64)
    return
  }

  const payload: PrintCommandPayload = {
    job_id: makeJobId(),
    sent_at: nowIso(),
    printer_name: printerName,
    payload_type: 'image',
    payload_encoding: 'data_url',
    payload: imageDataURL,
  }
  await publishCommand(printerName, payload)
}

export async function publishBase64PNGCommand(printerName: string, base64PNG: string): Promise<void> {
  if (base64PNG.length > IMAGE_CHUNK_SIZE) {
    const jobId = makeJobId()
    const total = Math.ceil(base64PNG.length / IMAGE_CHUNK_SIZE)
    for (let i = 0; i < total; i++) {
      const start = i * IMAGE_CHUNK_SIZE
      const end = Math.min(start + IMAGE_CHUNK_SIZE, base64PNG.length)
      const chunkPayload: PrintCommandPayload = {
        job_id: jobId,
        sent_at: nowIso(),
        printer_name: printerName,
        payload_type: 'image',
        payload_encoding: 'base64_chunk',
        payload: base64PNG.slice(start, end),
        chunk_index: i,
        chunks_total: total,
      }
      await publishCommand(printerName, chunkPayload)
    }
    return
  }

  const payload: PrintCommandPayload = {
    job_id: makeJobId(),
    sent_at: nowIso(),
    printer_name: printerName,
    payload_type: 'image',
    payload_encoding: 'base64_png',
    payload: base64PNG,
  }
  await publishCommand(printerName, payload)
}

export async function publishZPLCommand(printerName: string, zpl: string): Promise<void> {
  if (zpl.length > ZPL_CHUNK_SIZE) {
    const jobId = makeJobId()
    const chunks = chunkStringSafely(zpl, ZPL_CHUNK_SIZE)
    for (let i = 0; i < chunks.length; i++) {
      const chunkPayload: PrintCommandPayload = {
        job_id: jobId,
        sent_at: nowIso(),
        printer_name: printerName,
        payload_type: 'zpl',
        payload_encoding: 'utf8_chunk',
        payload: chunks[i],
        chunk_index: i,
        chunks_total: chunks.length,
      }
      await publishCommand(printerName, chunkPayload)
    }
    return
  }

  const payload: PrintCommandPayload = {
    job_id: makeJobId(),
    sent_at: nowIso(),
    printer_name: printerName,
    payload_type: 'zpl',
    payload_encoding: 'utf8',
    payload: zpl,
  }
  await publishCommand(printerName, payload)
}

export async function waitForInitialDiscovery(waitMs: number): Promise<void> {
  if (discovered.size > 0) return
  await new Promise<void>(resolve => {
    window.setTimeout(resolve, waitMs)
  })
}

export function getRemoteFonts(): FontInfo[] | null {
  return remoteFonts
}

export function onSharedFontsChanged(listener: () => void): () => void {
  sharedFontsListeners.add(listener)
  return () => sharedFontsListeners.delete(listener)
}

export async function waitForSharedFonts(waitMs: number): Promise<void> {
  if (remoteFonts !== null) return
  await new Promise<void>(resolve => {
    window.setTimeout(resolve, waitMs)
  })
}

export function publishSharedFonts(fonts: FontInfo[]): Promise<void> {
  ensureConnected()
  return new Promise<void>((resolve, reject) => {
    client?.publish(SHARED_FONTS_TOPIC, JSON.stringify(fonts), { qos: 1, retain: true }, err => {
      if (err) reject(err)
      else resolve()
    })
  })
}

export function getRemoteStats(): PrintStats | null {
  return remoteStats
}

export function onSharedStatsChanged(listener: () => void): () => void {
  sharedStatsListeners.add(listener)
  return () => sharedStatsListeners.delete(listener)
}

export async function waitForSharedStats(waitMs: number): Promise<void> {
  if (remoteStats !== null) return
  await new Promise<void>(resolve => {
    window.setTimeout(resolve, waitMs)
  })
}

export function publishSharedStats(stats: PrintStats): Promise<void> {
  ensureConnected()
  return new Promise<void>((resolve, reject) => {
    client?.publish(SHARED_STATS_TOPIC, JSON.stringify(stats), { qos: 1, retain: true }, err => {
      if (err) reject(err)
      else resolve()
    })
  })
}

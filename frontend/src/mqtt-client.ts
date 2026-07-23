import mqtt, { type MqttClient } from 'mqtt'
import type { FontInfo, MQTTFrontendConfig, PrinterInfo, PrinterStatusMessage, SharedAppConfig } from './types'

interface DiscoveredPrinter {
  printer: PrinterInfo
  printerName: string
  online: boolean
  busy: boolean
  lastError: string | null
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

// Retained topic the Settings-tab admin panel publishes to, so app-level
// settings (name, subtitle, ZPL example/template, feature toggles) apply to
// every browser that connects to the broker instead of only the one that
// saved them in localStorage. Broker connection fields (brokerURL/username/
// password) deliberately stay local-only -- you need them already to reach
// this topic in the first place, and config.json already ships the same
// default to every visitor.
const SHARED_APP_CONFIG_TOPIC = '/_stikka/app-config/'

let remoteAppConfig: SharedAppConfig | null = null
const sharedConfigListeners = new Set<() => void>()

function notifySharedConfigListeners(): void {
  for (const listener of sharedConfigListeners) listener()
}

// Retained topic for fonts uploaded via the Settings tab, so a font one
// visitor uploads becomes available to every browser instead of only the
// one that saved it locally. Unlike the ESP32 status/command topics, this
// is browser-to-browser only -- the firmware never subscribes here -- so
// the firmware's 65535-byte MQTT buffer ceiling doesn't apply; fonts go out
// as a single message regardless of size.
const SHARED_FONTS_TOPIC = '/_stikka/fonts/'

let remoteFonts: FontInfo[] | null = null
const sharedFontsListeners = new Set<() => void>()

function notifySharedFontsListeners(): void {
  for (const listener of sharedFontsListeners) listener()
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

function setDiscoveredPrinter(name: string, message: PrinterStatusMessage): void {
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
  }
  discovered.set(name, entry)
  notifyStatusListeners()
}

function subscribeStatusTopics(cfg: MQTTFrontendConfig): void {
  if (!client) return
  const wildcard = '/+/status/#'
  client.subscribe(wildcard, { qos: 1 }, err => {
    if (err) console.error('MQTT status subscribe failed:', err)
  })
  client.subscribe(SHARED_APP_CONFIG_TOPIC, { qos: 1 }, err => {
    if (err) console.error('MQTT shared app config subscribe failed:', err)
  })
  client.subscribe(SHARED_FONTS_TOPIC, { qos: 1 }, err => {
    if (err) console.error('MQTT shared fonts subscribe failed:', err)
  })
}

function onMessage(topic: string, payload: Uint8Array): void {
  if (topic === SHARED_APP_CONFIG_TOPIC) {
    try {
      const text = new TextDecoder().decode(payload)
      remoteAppConfig = text ? (JSON.parse(text) as SharedAppConfig) : null
    } catch (err) {
      console.warn('Ignoring malformed shared app config payload:', err)
    }
    notifySharedConfigListeners()
    return
  }

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
    setDiscoveredPrinter(json.printer_name ?? json.name ?? printerName, json)
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
  remoteAppConfig = null
  remoteFonts = null
  notifyStatusListeners()
  notifySharedConfigListeners()
  notifySharedFontsListeners()

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

  client.on('message', (topic, payload) => onMessage(topic, payload))
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

export function getRemoteAppConfig(): SharedAppConfig | null {
  return remoteAppConfig
}

export function onSharedAppConfigChanged(listener: () => void): () => void {
  sharedConfigListeners.add(listener)
  return () => sharedConfigListeners.delete(listener)
}

export async function waitForSharedAppConfig(waitMs: number): Promise<void> {
  if (remoteAppConfig !== null) return
  await new Promise<void>(resolve => {
    window.setTimeout(resolve, waitMs)
  })
}

export function publishSharedAppConfig(config: SharedAppConfig): Promise<void> {
  ensureConnected()
  return new Promise<void>((resolve, reject) => {
    client?.publish(SHARED_APP_CONFIG_TOPIC, JSON.stringify(config), { qos: 1, retain: true }, err => {
      if (err) reject(err)
      else resolve()
    })
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

import mqtt, { type MqttClient } from 'mqtt'
import type { MQTTFrontendConfig, PrinterStatusMessage } from './types'
import { upsertSupabasePrinter } from './supabase-client'

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

const statusListeners = new Set<() => void>()

function notifyStatusListeners(): void {
  for (const listener of statusListeners) listener()
}

// Firmware falls back to this name (main.cpp) when a device hasn't been
// given a unique printer name yet. It's not unique across devices, so
// treating it as a real discoverable printer risks sending a job to the
// wrong (or multiple) unconfigured units. Ignore status from it entirely.
const DEFAULT_PRINTER_NAME = 'stikka-esp32'

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

function subscribeStatusTopics(): void {
  if (!client) return
  client.subscribe('/+/status/#', { qos: 1 }, err => {
    if (err) console.error('MQTT status subscribe failed:', err)
  })
}

// Full status snapshots (buildStatusJson() in main.cpp) get relayed into
// Supabase (see supabase-client.ts) instead of kept in a local map -- every
// browser reads the shared printers table there, so discovery/pruning state
// is consistent across browsers and unaffected by any single page reload.
function onMessage(topic: string, payload: Uint8Array, isRetainedReplay: boolean): void {
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
    // info with default label/capability values on every print.
    if (json.phase === undefined) return
    const resolvedName = json.printer_name ?? json.name ?? printerName
    if (resolvedName.toLowerCase() === DEFAULT_PRINTER_NAME) return
    void upsertSupabasePrinter(resolvedName, json, isRetainedReplay)
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
  notifyStatusListeners()

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
      subscribeStatusTopics()
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
    subscribeStatusTopics()
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

  client.on('message', (topic, payload, packet) => onMessage(topic, payload, packet.retain))
}

export function onMQTTStatusChanged(listener: () => void): () => void {
  statusListeners.add(listener)
  return () => statusListeners.delete(listener)
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

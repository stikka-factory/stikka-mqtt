import mqtt, { type MqttClient } from 'mqtt'
import type { MQTTFrontendConfig, PrinterInfo, PrinterStatusMessage } from './types'

const DEFAULT_STATUS_PREFIX = '/status'
const DEFAULT_COMMAND_PREFIX = '/command'

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
  payload_encoding: 'data_url' | 'utf8' | 'base64_png'
  payload: string
}

let client: MqttClient | null = null
let mqttConfig: MQTTFrontendConfig | null = null
let connected = false

const discovered = new Map<string, DiscoveredPrinter>()
const statusListeners = new Set<() => void>()

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

function withPrefix(base: string, printerName?: string): string {
  if (!printerName) return base
  const normalizedBase = base.endsWith('/') ? base.slice(0, -1) : base
  return `${normalizedBase}/${printerName}`
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
  const statusPrefix = cfg.statusTopicPrefix ?? DEFAULT_STATUS_PREFIX
  const wildcard = withPrefix(statusPrefix, '+')
  client.subscribe(wildcard, { qos: 1 }, err => {
    if (err) console.error('MQTT status subscribe failed:', err)
  })
}

function onMessage(topic: string, payload: Uint8Array): void {
  const cfg = mqttConfig
  if (!cfg) return
  const statusPrefix = cfg.statusTopicPrefix ?? DEFAULT_STATUS_PREFIX
  const prefix = statusPrefix.endsWith('/') ? statusPrefix : `${statusPrefix}/`
  if (!topic.startsWith(prefix)) return

  const printerName = topic.slice(prefix.length).split('/')[0]
  if (!printerName) return

  try {
    const text = new TextDecoder().decode(payload)
    const json = JSON.parse(text) as PrinterStatusMessage
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
  discovered.clear()
  notifyStatusListeners()

  mqttConfig = cfg

  const clientIdPrefix = cfg.clientIdPrefix ?? 'stikka-web'
  client = mqtt.connect(cfg.brokerURL, {
    clientId: randomClientId(clientIdPrefix),
    username: cfg.username,
    password: cfg.password,
    reconnectPeriod: 3000,
    keepalive: 30,
    clean: true,
  })

  await new Promise<void>((resolve, reject) => {
    if (!client) {
      reject(new Error('MQTT client was not initialized'))
      return
    }

    const cleanup = (): void => {
      client?.off('connect', onConnect)
      client?.off('error', onError)
    }

    const onConnect = (): void => {
      cleanup()
      connected = true
      subscribeStatusTopics(cfg)
      resolve()
    }

    const onError = (err: Error): void => {
      cleanup()
      reject(err)
    }

    client.on('connect', onConnect)
    client.on('error', onError)
  })

  client.on('connect', () => {
    connected = true
    subscribeStatusTopics(cfg)
  })

  client.on('close', () => {
    connected = false
  })

  client.on('message', (topic, payload) => onMessage(topic, payload))
}

export async function updateMQTTTransport(cfg: MQTTFrontendConfig): Promise<void> {
  await initMQTTTransport(cfg)
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

function ensureConnected(): void {
  if (!client || !connected || !mqttConfig) {
    throw new Error('MQTT is not connected')
  }
}

function publishCommand(printerName: string, payload: PrintCommandPayload): Promise<void> {
  ensureConnected()
  const commandPrefix = mqttConfig?.commandTopicPrefix ?? DEFAULT_COMMAND_PREFIX
  const topic = withPrefix(commandPrefix, printerName)
  return new Promise<void>((resolve, reject) => {
    client?.publish(topic, JSON.stringify(payload), { qos: 1 }, err => {
      if (err) reject(err)
      else resolve()
    })
  })
}

export async function publishImageCommand(printerName: string, imageDataURL: string): Promise<void> {
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

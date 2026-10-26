// Transport for "server" mode: the web app talks to stikka-server over HTTPS
// and one WebSocket (/api/ws) for live updates, instead of an MQTT broker
// plus Supabase. Printer status, fonts and stats all come from the server.
// See github.com/stikka-factory/stikka-server for the API.

import type { FontInfo, PrintStats, PrinterInfo } from './types'

// One printer as GET /api/printers and the printer.updated event return it
// (PrinterView in stikka-server's hub.ts).
interface ServerPrinter {
  node_id: string
  name: string
  online: boolean
  state: string
  error: { code: string; message?: string } | null
  printer: {
    protocol?: string
    dpi?: number
    label?: Partial<PrinterInfo['label']>
    capabilities?: Record<string, unknown>
  } | null
  roll: { state: 'ok' | 'low' | 'empty'; source: string } | null
  location: { lat: number; lon: number } | null
}

export interface ServerPrinterEntry {
  printer: PrinterInfo
  online: boolean
  busy: boolean
  lastError: string | null
  roll: 'ok' | 'low' | 'empty'
}

type ServerEvent =
  | { type: 'snapshot'; printers: ServerPrinter[]; stats: PrintStats }
  | { type: 'printer.updated'; printer: ServerPrinter }
  | { type: 'printer.removed'; node_id: string }
  | { type: 'stats.updated'; stats: PrintStats }
  | { type: 'fonts.updated' }
  | { type: 'job.updated' }

let baseURL = ''
let socket: WebSocket | null = null
let connected = false
let lastError: string | null = null
let reconnectAttempt = 0
const printers = new Map<string, ServerPrinter>()
let stats: PrintStats | null = null

const printerListeners = new Set<() => void>()
const statsListeners = new Set<() => void>()
const connectionListeners = new Set<() => void>()

function notify(listeners: Set<() => void>): void {
  for (const listener of listeners) listener()
}

function num(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function bool(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback
}

// Same defaults upsertSupabasePrinter() applies to an MQTT status snapshot,
// so a printer renders the same whichever transport reported it.
function toPrinterInfo(p: ServerPrinter, index: number): PrinterInfo {
  const label = p.printer?.label ?? {}
  const caps = p.printer?.capabilities ?? {}
  return {
    index,
    nodeId: p.node_id,
    name: p.name,
    serial: '',
    location: p.location ? `${p.location.lat.toFixed(5)}, ${p.location.lon.toFixed(5)}` : '',
    type: p.printer?.protocol ?? 'zpl',
    dpi: num(p.printer?.dpi, 203),
    label: {
      width: num(label.width, 80),
      length: num(label.length, 80),
      isRound: bool(label.isRound, false),
      verticalOffset: num(label.verticalOffset, 0),
      cut: bool(label.cut, false),
    },
    zplCompressionSupported: bool(caps.zplCompression, false),
    qlPrintheadPx: num(caps.qlPrintheadPx, 720),
    qlInvalidateBytes: num(caps.qlInvalidateBytes, 200),
    qlAutoCut: bool(caps.qlAutoCut, true),
    qlFeedMarginDots: num(caps.qlFeedMarginDots, 35),
    qlRightMarginDots: num(caps.qlRightMarginDots, 0),
    seikoMaxDots: num(caps.seikoMaxDots, 576),
    seikoDensity: num(caps.seikoDensity, 0),
    seikoSpeed: num(caps.seikoSpeed, 2),
  }
}

export function getServerPrinterEntries(): ServerPrinterEntry[] {
  return [...printers.values()]
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }))
    .map((p, index) => ({
      printer: toPrinterInfo(p, index),
      online: p.online,
      busy: p.state === 'printing',
      lastError: p.error ? (p.error.message ?? p.error.code) : null,
      roll: p.roll?.state ?? 'ok',
    }))
}

function url(path: string): string {
  return `${baseURL}${path}`
}

function wsURL(): string {
  const u = new URL(url('/api/ws'), window.location.href)
  u.protocol = u.protocol === 'https:' ? 'wss:' : 'ws:'
  return u.toString()
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url(path), init)
  const text = await res.text()
  const body = text ? JSON.parse(text) : null
  if (!res.ok) throw new Error(body?.message ?? body?.error ?? `HTTP ${res.status}`)
  return body as T
}

function onEvent(event: ServerEvent): void {
  switch (event.type) {
    case 'snapshot':
      printers.clear()
      for (const p of event.printers) printers.set(p.node_id, p)
      stats = event.stats
      notify(printerListeners)
      notify(statsListeners)
      break
    case 'printer.updated':
      printers.set(event.printer.node_id, event.printer)
      notify(printerListeners)
      break
    case 'printer.removed':
      printers.delete(event.node_id)
      notify(printerListeners)
      break
    case 'stats.updated':
      stats = event.stats
      notify(statsListeners)
      break
  }
}

function setConnected(value: boolean, error: string | null): void {
  connected = value
  lastError = error
  notify(connectionListeners)
}

function openSocket(onFirstSnapshot?: () => void): void {
  const ws = new WebSocket(wsURL())
  socket = ws
  ws.addEventListener('open', () => {
    reconnectAttempt = 0
    setConnected(true, null)
  })
  ws.addEventListener('message', e => {
    try {
      const event = JSON.parse(String(e.data)) as ServerEvent
      onEvent(event)
      if (event.type === 'snapshot' && onFirstSnapshot) {
        onFirstSnapshot()
        onFirstSnapshot = undefined
      }
    } catch (err) {
      console.warn('Ignoring malformed server event:', err)
    }
  })
  ws.addEventListener('close', () => {
    if (socket !== ws) return
    const delayS = Math.min(30, 2 ** reconnectAttempt++)
    setConnected(false, `reconnecting in ${delayS}s`)
    window.setTimeout(() => openSocket(onFirstSnapshot), delayS * 1000)
  })
}

// Resolves once the first snapshot (printers + stats) has arrived, or after
// a few seconds so a slow or unreachable server doesn't block the UI.
export async function initServerTransport(serverURL: string): Promise<void> {
  baseURL = serverURL.replace(/\/+$/, '')
  if (socket) {
    const old = socket
    socket = null
    old.close()
  }
  await new Promise<void>(resolve => {
    const timer = window.setTimeout(resolve, 5000)
    openSocket(() => {
      window.clearTimeout(timer)
      resolve()
    })
  })
}

export function getServerBaseURL(): string {
  return baseURL || window.location.origin
}

export function isServerConnected(): boolean {
  return connected
}

export function getServerLastError(): string | null {
  return lastError
}

export function onServerPrintersChanged(listener: () => void): () => void {
  printerListeners.add(listener)
  return () => printerListeners.delete(listener)
}

export function onServerStatsChanged(listener: () => void): () => void {
  statsListeners.add(listener)
  return () => statsListeners.delete(listener)
}

export function onServerConnectionChanged(listener: () => void): () => void {
  connectionListeners.add(listener)
  return () => connectionListeners.delete(listener)
}

export async function fetchServerStats(): Promise<PrintStats> {
  stats = await request<PrintStats>('/api/stats')
  return stats
}

export function getCachedServerStats(): PrintStats | null {
  return stats
}

export async function recordServerPrint(kind: string): Promise<void> {
  await request('/api/stats/record', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ kind }),
  })
}

export async function fetchServerFonts(): Promise<FontInfo[]> {
  const { fonts } = await request<{ fonts: Array<{ name: string; url: string }> }>('/api/fonts')
  return fonts.map(f => ({ name: f.name, path: url(f.url) }))
}

export async function uploadServerFont(name: string, file: File): Promise<FontInfo> {
  const form = new FormData()
  form.append('name', name)
  form.append('file', file, file.name)
  const font = await request<{ name: string; url: string }>('/api/fonts', { method: 'POST', body: form })
  return { name: font.name, path: url(font.url) }
}

// The server queues the job for up to 5 minutes if the printer is offline
// and expires it after that, so this resolves once the job is accepted, not
// once it has printed (same as publishing over MQTT did).
export async function sendServerJob(
  nodeId: string,
  payloadType: 'zpl' | 'image' | 'ql_raster' | 'seiko_raster',
  payloadEncoding: 'utf8' | 'data_url' | 'base64_bytes',
  payload: string,
): Promise<void> {
  await request('/api/jobs', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ node_id: nodeId, payload_type: payloadType, payload_encoding: payloadEncoding, payload }),
  })
}

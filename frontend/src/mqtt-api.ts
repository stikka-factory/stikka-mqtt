import type {
  PrinterInfo,
  FontInfo,
  AppInfo,
  PrintStats,
  ImageSourceKind,
  StaticModeConfig,
  MQTTFrontendConfig,
} from './types'
import {
  initMQTTTransport,
  publishImageCommand,
  publishQLRasterCommand,
  publishSeikoRasterCommand,
  publishZPLCommand,
  onMQTTStatusChanged,
  isMQTTConnected,
  getMQTTLastError,
} from './mqtt-client'
import {
  initSupabaseTransport,
  fetchSupabaseFonts,
  uploadSupabaseFont,
  fetchSupabaseStats,
  recordSupabasePrint,
  subscribeSupabaseStats,
  fetchSupabasePrinters,
  subscribeSupabasePrinters,
  type SupabasePrinterEntry,
} from './supabase-client'
import {
  initServerTransport,
  getServerPrinterEntries,
  getServerBaseURL,
  isServerConnected,
  getServerLastError,
  onServerPrintersChanged,
  onServerStatsChanged,
  onServerConnectionChanged,
  fetchServerStats,
  getCachedServerStats,
  recordServerPrint,
  fetchServerFonts,
  uploadServerFont,
  sendServerJob,
  type ServerPrinterEntry,
} from './server-client'
import { imageDataURLToQLRasterBase64, imageDataURLToSeikoRasterBase64, imageDataURLToZPL } from './zpl-image'
import readmeMarkdown from '../../README.md?raw'

let fallbackPrinters: PrinterInfo[] = []
let fallbackAppInfo: AppInfo | null = null
let mqttRuntimeConfig: MQTTFrontendConfig | null = null
// 'mqtt': MQTT broker for jobs/status + Supabase for storage (GitHub Pages
// deploy). 'server': everything through stikka-server.
let transportMode: 'mqtt' | 'server' = 'mqtt'
let sharedFonts: FontInfo[] = []

function delay(ms: number): Promise<void> {
  return new Promise(resolve => window.setTimeout(resolve, ms))
}

function zeroStats(): PrintStats {
  return {
    printed_total: 0,
    printed_cats: 0,
    printed_dogs: 0,
    printed_dinos: 0,
    printed_uploaded_images: 0,
    printed_webcam_images: 0,
    printed_without_image: 0,
  }
}

let cachedStats: PrintStats = zeroStats()
const statsListeners = new Set<() => void>()

let cachedPrinterEntries: Array<SupabasePrinterEntry | ServerPrinterEntry> = []
const printerListeners = new Set<() => void>()
let printerRefreshIntervalId: number | null = null

// Age-based staleness (fetchSupabasePrinters()'s last_seen cutoff) can flip
// a printer from present to gone without any row actually changing, so a
// realtime subscription alone isn't enough -- also poll on this interval,
// same cadence the old client-side prune timer used.
const PRINTER_REFRESH_INTERVAL_MS = 30 * 1000

const DUMMY_PRINTER_NAME = 'mqtt-dummy'

function dummyPrinter(): PrinterInfo {
  return {
    index: 0,
    name: DUMMY_PRINTER_NAME,
    serial: '',
    location: '',
    type: 'zpl',
    dpi: 203,
    label: {
      width: 55,
      length: 55,
      isRound: false,
      verticalOffset: 0,
      cut: false,
    },
    zplCompressionSupported: false,
    qlPrintheadPx: 720,
    qlInvalidateBytes: 200,
    qlAutoCut: true,
    qlFeedMarginDots: 35,
    qlRightMarginDots: 0,
    seikoMaxDots: 576,
    seikoDensity: 0,
    seikoSpeed: 2,
  }
}

// config.json picks the transport. mode "server": stikka-server serves
// config.json itself (from its APP_* env vars) and handles printers, fonts
// and stats. mode "mqtt": written by .github/workflows/deploy-pages.yml from
// repo Variables/Secrets, the only source for app.*/mqtt.*/supabase.*
// settings -- there's no in-app editor for them, so changing a deployment's
// config means changing repo Variables/Secrets and redeploying (see
// CLAUDE.md). MQTT remains the ingestion path for printer status (it's the
// only channel the ESP32 firmware speaks), but fonts/stats/printer-discovery
// storage all live in Supabase now -- see supabase-client.ts and
// supabase/schema.sql.
export async function initTransport(config: StaticModeConfig): Promise<void> {
  fallbackAppInfo = config.app
  transportMode = config.mode

  if (config.mode === 'server') {
    // No dummy-printer fallback here: the server knows every enrolled
    // printer, so an empty list really means none are enrolled.
    await initServerTransport(config.server?.url ?? '')
    const syncPrinters = () => {
      cachedPrinterEntries = getServerPrinterEntries()
      for (const listener of printerListeners) listener()
    }
    const syncStats = () => {
      cachedStats = getCachedServerStats() ?? cachedStats
      for (const listener of statsListeners) listener()
    }
    syncPrinters()
    syncStats()
    onServerPrintersChanged(syncPrinters)
    onServerStatsChanged(syncStats)
    return
  }

  if (!config.mqtt?.brokerURL) {
    throw new Error('Missing mqtt.brokerURL in config.json')
  }
  if (!config.supabase?.url || !config.supabase?.anonKey) {
    throw new Error('Missing supabase.url/anonKey in config.json')
  }

  fallbackPrinters = [dummyPrinter()]

  initSupabaseTransport(config.supabase)

  mqttRuntimeConfig = { ...config.mqtt }
  await initMQTTTransport(mqttRuntimeConfig)

  // initMQTTTransport() resolves as soon as the broker connection is up and
  // the wildcard status subscribe has been fired -- it does not wait for the
  // retained /+/status/# replies to actually arrive and get relayed into
  // Supabase (upsertSupabasePrinter() in mqtt-client.ts, fired from the
  // async 'message' event). Without this wait, the fetch below races that
  // relay and can see an empty/stale printer list until the next 30s poll or
  // a reload happens to land after the relay completes.
  await delay(mqttRuntimeConfig.discoveryWaitMs ?? 1500)

  await refreshPrinters()
  subscribeSupabasePrinters(() => { void refreshPrinters() })
  if (printerRefreshIntervalId === null) {
    printerRefreshIntervalId = window.setInterval(() => { void refreshPrinters() }, PRINTER_REFRESH_INTERVAL_MS)
  }

  await refreshStats()
  subscribeSupabaseStats(() => { void refreshStats() })
}

async function refreshPrinters(): Promise<void> {
  try {
    cachedPrinterEntries = await fetchSupabasePrinters()
  } catch (e) {
    console.warn('Could not fetch printers from Supabase:', e)
  }
  for (const listener of printerListeners) listener()
}

async function refreshStats(): Promise<void> {
  try {
    cachedStats = transportMode === 'server' ? await fetchServerStats() : await fetchSupabaseStats()
  } catch (e) {
    console.warn('Could not fetch print statistics from Supabase:', e)
  }
  for (const listener of statsListeners) listener()
}

function currentPrinters(): PrinterInfo[] {
  if (cachedPrinterEntries.length > 0) return cachedPrinterEntries.map(e => e.printer)
  return transportMode === 'server' ? [] : fallbackPrinters
}

function pickPrinter(printerIndex: number): PrinterInfo {
  const printers = currentPrinters()
  const selected = printers[printerIndex] ?? printers.find(p => p.index === printerIndex)
  if (!selected) throw new Error('No printer found at selected index')
  return selected
}

// Server mode addresses printers by node_id; MQTT mode by name (topic).
function serverNodeId(printer: PrinterInfo): string {
  if (!printer.nodeId) throw new Error(`Printer ${printer.name} has no node id`)
  return printer.nodeId
}

async function sendZPL(printer: PrinterInfo, zpl: string): Promise<void> {
  logZPLBeforeSend(printer.name, zpl)
  if (transportMode === 'server') return sendServerJob(serverNodeId(printer), 'zpl', 'utf8', zpl)
  return publishZPLCommand(printer.name, zpl)
}

async function sendQLRaster(printer: PrinterInfo, base64: string): Promise<void> {
  if (transportMode === 'server') return sendServerJob(serverNodeId(printer), 'ql_raster', 'base64_bytes', base64)
  return publishQLRasterCommand(printer.name, base64)
}

async function sendSeikoRaster(printer: PrinterInfo, base64: string): Promise<void> {
  if (transportMode === 'server') return sendServerJob(serverNodeId(printer), 'seiko_raster', 'base64_bytes', base64)
  return publishSeikoRasterCommand(printer.name, base64)
}

async function sendImage(printer: PrinterInfo, imageDataURL: string): Promise<void> {
  if (transportMode === 'server') return sendServerJob(serverNodeId(printer), 'image', 'data_url', imageDataURL)
  return publishImageCommand(printer.name, imageDataURL)
}

export async function fetchAppInfo(): Promise<AppInfo> {
  return fallbackAppInfo ?? {
    name: 'Stikka-NG',
    subtitle: 'MQTT Mode',
    zplExample: '^XA\n^CFA,30\n^FO50,20\n^FDStikka MQTT Test^FS\n^XZ',
    zplRawEnabled: true,
    cableLabelEnabled: false,
    textOverlayEnabled: true,
  }
}

export async function fetchPrinters(): Promise<PrinterInfo[]> {
  return currentPrinters()
}

export async function fetchFonts(): Promise<FontInfo[]> {
  const indexURL = `${import.meta.env.BASE_URL}fonts/index.json`
  let builtIn: FontInfo[] = []
  try {
    const res = await fetch(indexURL, { cache: 'no-store' })
    if (res.ok) {
      const data = await res.json() as { fonts?: Array<{ name: string; path: string }> }
      builtIn = (data.fonts ?? []).map(f => ({
        name: f.name,
        path: `${import.meta.env.BASE_URL}fonts/${f.path}`,
      }))
    }
  } catch {
    builtIn = []
  }

  // Fonts uploaded via the Fonts tab live in Supabase (table + Storage
  // bucket, see supabase-client.ts) so they're available to every browser,
  // not just the one that uploaded them. They win over a built-in font of
  // the same name.
  try {
    sharedFonts = transportMode === 'server' ? await fetchServerFonts() : await fetchSupabaseFonts()
  } catch (e) {
    console.warn('Could not fetch shared fonts:', e)
  }
  return [...builtIn.filter(f => !sharedFonts.some(s => s.name === f.name)), ...sharedFonts]
}

// Uploads a font's raw bytes to Supabase Storage and records it (added to
// whatever's already shared) so every connected browser picks it up, instead
// of it staying local to the uploader.
export async function publishFont(name: string, file: File): Promise<FontInfo> {
  const font = transportMode === 'server' ? await uploadServerFont(name, file) : await uploadSupabaseFont(name, file)
  sharedFonts = [...sharedFonts.filter(f => f.name !== font.name), font]
  return font
}

export async function printImage(printerIndex: number, imageDataURL: string): Promise<void> {
  const printer = pickPrinter(printerIndex)
  console.log(`[print] printImage: printer=${printer.name} type=${printer.type} dpi=${printer.dpi} label=${printer.label.width}x${printer.label.length}mm sourceDataURL=${imageDataURL.length} chars`)

  if (printer.type === 'brother_ql' || printer.type === 'ql') {
    const base64 = await imageDataURLToQLRasterBase64(imageDataURL, {
      printheadPx: printer.qlPrintheadPx,
      invalidateBytes: printer.qlInvalidateBytes,
      autoCut: printer.qlAutoCut,
      feedMarginDots: printer.qlFeedMarginDots,
      rightMarginDots: printer.qlRightMarginDots,
      labelWidthMm: printer.label.width,
      labelLengthMm: printer.label.length,
    })
    console.log(`[print] ql: sending raster, ${base64.length} base64 bytes`)
    await sendQLRaster(printer, base64)
    return
  }

  if (printer.type === 'seiko_slp' || printer.type === 'seiko') {
    const base64 = await imageDataURLToSeikoRasterBase64(imageDataURL, {
      maxDots: printer.seikoMaxDots,
      density: printer.seikoDensity,
      speed: printer.seikoSpeed,
      dpi: printer.dpi,
      labelWidthMm: printer.label.width,
      labelLengthMm: printer.label.length,
    })
    console.log(`[print] seiko: sending raster, ${base64.length} base64 bytes`)
    await sendSeikoRaster(printer, base64)
    return
  }

  if (printer.type === 'zpl' || printer.type === 'zebra') {
    const zpl = await imageDataURLToZPL(
      imageDataURL,
      printer.dpi,
      printer.label.width,
      printer.label.length,
      printer.label.verticalOffset,
      printer.zplCompressionSupported,
    )
    await sendZPL(printer, zpl)
    return
  }

  await sendImage(printer, imageDataURL)
}

export async function sendRawZPL(printerIndex: number, zpl: string): Promise<void> {
  await sendZPL(pickPrinter(printerIndex), zpl)
}

function logZPLBeforeSend(printerName: string, zpl: string): void {
  console.log(`[print] sending ZPL to ${printerName}, length=${zpl.length} chars`)
  console.log(zpl)
}

export async function previewZPL(printerIndex: number, zpl: string): Promise<string> {
  const printer = pickPrinter(printerIndex)
  const dpmm = Math.max(6, Math.round(printer.dpi / 25.4))
  const widthIn = Math.max(0.2, printer.label.width / 25.4)
  const lengthMm = printer.label.length > 0 ? printer.label.length : 76.2
  const heightIn = Math.max(0.2, lengthMm / 25.4)
  const encodedZPL = encodeURIComponent(zpl)
  return `https://api.labelary.com/v1/printers/${dpmm}dpmm/labels/${widthIn.toFixed(3)}x${heightIn.toFixed(3)}/0/${encodedZPL}`
}

// cdn2.thecatapi.com and images.dinosaurpictures.org don't send Access-Control-Allow-Origin,
// so <img crossorigin="anonymous"> (needed for canvas readback/dithering) fails to load them
// silently. Route those two through a CORS-adding image proxy; dog.ceo already sends the
// header itself and needs no proxying.
function corsProxyImageURL(url: string): string {
  return `https://images.weserv.nl/?url=${encodeURIComponent(url.replace(/^https?:\/\//, ''))}`
}

export async function fetchRandomImage(kind: 'cat' | 'dog' | 'dino'): Promise<string> {
  if (kind === 'cat') {
    const catRes = await fetch('https://api.thecatapi.com/v1/images/search')
    if (!catRes.ok) throw new Error(`Fetch cat metadata failed: ${catRes.status}`)
    const catData = await catRes.json() as Array<{ url?: string }>
    const catURL = catData?.[0]?.url
    if (!catURL) throw new Error('Cat API returned no image URL')
    return corsProxyImageURL(catURL)
  }

  if (kind === 'dog') {
    const dogRes = await fetch('https://dog.ceo/api/breeds/image/random')
    if (!dogRes.ok) throw new Error(`Fetch dog metadata failed: ${dogRes.status}`)
    const dogData = await dogRes.json() as { message?: string }
    if (!dogData.message) throw new Error('Dog API returned no image URL')
    return dogData.message
  }

  const dinoRes = await fetch(`https://dinosaurpictures.org/api/dinosaur/random?_=${Date.now()}`)
  if (!dinoRes.ok) throw new Error(`Fetch dino metadata failed: ${dinoRes.status}`)
  const dinoData = await dinoRes.json() as { pics?: Array<{ url?: string }> }
  const dinoURL = dinoData?.pics?.[0]?.url
  if (!dinoURL) throw new Error('Dino API returned no image URL')
  return corsProxyImageURL(dinoURL)
}

// What the About tab shows the app is connected to.
export function getConnectionLabel(): string {
  if (transportMode === 'server') return `server ${getServerBaseURL()}`
  return `MQTT broker ${mqttRuntimeConfig?.brokerURL || '(unknown)'}`
}

export async function fetchStats(): Promise<PrintStats> {
  return { ...cachedStats }
}

// Tallies a completed print job via record_print() (supabase/schema.sql), a
// single atomic UPDATE -- unlike the old MQTT-retained read-modify-publish,
// concurrent prints from different browsers can no longer race and
// undercount. Best-effort: a failed call just leaves the print untallied
// rather than blocking the print flow.
export async function recordPrint(kind: ImageSourceKind): Promise<void> {
  try {
    if (transportMode === 'server') {
      // The server broadcasts the new totals; no refetch needed.
      await recordServerPrint(kind)
    } else {
      await recordSupabasePrint(kind)
      await refreshStats()
    }
  } catch (e) {
    console.warn('Could not record print statistics:', e)
  }
}

export function subscribeSharedStats(onChange: (stats: PrintStats) => void): () => void {
  const listener = () => onChange({ ...cachedStats })
  statsListeners.add(listener)
  return () => statsListeners.delete(listener)
}

export async function fetchReadme(): Promise<string> {
  return readmeMarkdown
}

// Printer list comes from Supabase in MQTT mode and from the server's live
// WebSocket in server mode (see initTransport() above).
export function subscribePrinters(onChange: (printers: PrinterInfo[]) => void): () => void {
  const listener = () => onChange(currentPrinters())
  printerListeners.add(listener)
  return () => printerListeners.delete(listener)
}

// Distinct from subscribePrinters(): this fires on the connection itself
// (MQTT broker or server WebSocket: connect/disconnect/error), for UI that
// only cares about connection status (e.g. the About tab's banner).
export function subscribeConnection(onChange: () => void): () => void {
  return transportMode === 'server' ? onServerConnectionChanged(onChange) : onMQTTStatusChanged(onChange)
}

export interface PrinterMeta {
  online: boolean
  busy: boolean
  lastError: string | null
  // Only reported in server mode (roll sensor on the node); 'ok' otherwise.
  roll: 'ok' | 'low' | 'empty'
}

export function getPrinterMetaByIndex(printerIndex: number): PrinterMeta | null {
  const entry = cachedPrinterEntries[printerIndex]
  if (!entry) return null
  return { online: entry.online, busy: entry.busy, lastError: entry.lastError, roll: 'roll' in entry ? entry.roll : 'ok' }
}

export function getConnectionState(): { connected: boolean; lastError: string | null } {
  if (transportMode === 'server') return { connected: isServerConnected(), lastError: getServerLastError() }
  return {
    connected: isMQTTConnected(),
    lastError: getMQTTLastError(),
  }
}

export function isDummyPrinter(printerName: string): boolean {
  return printerName === DUMMY_PRINTER_NAME
}

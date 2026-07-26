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
  publishBase64PNGCommand,
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
import { imageDataURLToBase64PNG, imageDataURLToZPL } from './zpl-image'

let fallbackPrinters: PrinterInfo[] = []
let fallbackAppInfo: AppInfo | null = null
let mqttRuntimeConfig: MQTTFrontendConfig | null = null
let sharedFonts: FontInfo[] = []

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

let cachedPrinterEntries: SupabasePrinterEntry[] = []
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
  }
}

// config.json (written by .github/workflows/deploy-pages.yml from repo
// Variables/Secrets) is the only source for app.*/mqtt.*/supabase.*
// settings -- there's no in-app editor for them, so changing a deployment's
// config means changing repo Variables/Secrets and redeploying (see
// CLAUDE.md). MQTT remains the ingestion path for printer status (it's the
// only channel the ESP32 firmware speaks), but fonts/stats/printer-discovery
// storage all live in Supabase now -- see supabase-client.ts and
// supabase/schema.sql.
export async function initTransport(config: StaticModeConfig): Promise<void> {
  if (config.mode !== 'mqtt') {
    throw new Error('This fork supports only mqtt mode.')
  }
  if (!config.mqtt?.brokerURL) {
    throw new Error('Missing mqtt.brokerURL in config.json')
  }
  if (!config.supabase?.url || !config.supabase?.anonKey) {
    throw new Error('Missing supabase.url/anonKey in config.json')
  }

  fallbackPrinters = [dummyPrinter()]
  fallbackAppInfo = config.app

  initSupabaseTransport(config.supabase)

  mqttRuntimeConfig = { ...config.mqtt }
  await initMQTTTransport(mqttRuntimeConfig)

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
    cachedStats = await fetchSupabaseStats()
  } catch (e) {
    console.warn('Could not fetch print statistics from Supabase:', e)
  }
  for (const listener of statsListeners) listener()
}

function mqttPrinters(): PrinterInfo[] {
  if (cachedPrinterEntries.length > 0) return cachedPrinterEntries.map(e => e.printer)
  return fallbackPrinters
}

function pickPrinterName(printerIndex: number): string {
  const printers = mqttPrinters()
  const selected = printers[printerIndex] ?? printers.find(p => p.index === printerIndex)
  if (!selected) throw new Error('No MQTT printer found at selected index')
  return selected.name
}

function pickPrinter(printerIndex: number): PrinterInfo {
  const printers = mqttPrinters()
  const selected = printers[printerIndex] ?? printers.find(p => p.index === printerIndex)
  if (!selected) throw new Error('No MQTT printer found at selected index')
  return selected
}

export async function fetchAppInfo(): Promise<AppInfo> {
  return fallbackAppInfo ?? {
    name: 'Stikka-NG',
    subtitle: 'MQTT Mode',
    zplExample: '^XA\n^CFA,30\n^FO50,20\n^FDStikka MQTT Test^FS\n^XZ',
    zplRawEnabled: true,
    cableLabelEnabled: false,
  }
}

export async function fetchPrinters(): Promise<PrinterInfo[]> {
  return mqttPrinters()
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
    sharedFonts = await fetchSupabaseFonts()
  } catch (e) {
    console.warn('Could not fetch fonts from Supabase:', e)
  }
  return [...builtIn.filter(f => !sharedFonts.some(s => s.name === f.name)), ...sharedFonts]
}

// Uploads a font's raw bytes to Supabase Storage and records it (added to
// whatever's already shared) so every connected browser picks it up, instead
// of it staying local to the uploader.
export async function publishFont(name: string, file: File): Promise<FontInfo> {
  const font = await uploadSupabaseFont(name, file)
  sharedFonts = [...sharedFonts.filter(f => f.name !== font.name), font]
  return font
}

export async function printImage(printerIndex: number, imageDataURL: string): Promise<void> {
  const printer = pickPrinter(printerIndex)
  const printerName = printer.name

  if (printer.type === 'brother_ql' || printer.type === 'ql') {
    const base64 = imageDataURLToBase64PNG(imageDataURL)
    await publishBase64PNGCommand(printerName, base64)
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
    logZPLBeforeSend(printerName, zpl)
    await publishZPLCommand(printerName, zpl)
    return
  }

  await publishImageCommand(printerName, imageDataURL)
}

export async function sendRawZPL(printerIndex: number, zpl: string): Promise<void> {
  const printerName = pickPrinterName(printerIndex)
  logZPLBeforeSend(printerName, zpl)
  await publishZPLCommand(printerName, zpl)
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

export function getMQTTConfig(): MQTTFrontendConfig | null {
  if (!mqttRuntimeConfig) return null
  return { ...mqttRuntimeConfig }
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
    await recordSupabasePrint(kind)
    await refreshStats()
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
  return 'Static MQTT mode is active. Configure printers on each ESP32 device UI. Topics: /<printername>/status/ and /<printername>/command/.'
}

// Printer list now comes from Supabase (fonts/stats/discovery all do, see
// initTransport() above) -- the name stays "MQTT" since these are still the
// printers reachable over MQTT, just discovered via a shared table instead
// of this browser's own direct wildcard subscription.
export function subscribeMQTTPrinters(onChange: (printers: PrinterInfo[]) => void): () => void {
  const listener = () => onChange(mqttPrinters())
  printerListeners.add(listener)
  return () => printerListeners.delete(listener)
}

// Distinct from subscribeMQTTPrinters(): this fires on the MQTT broker
// connection itself (connect/disconnect/error), for UI that only cares
// about connection status (e.g. the About tab's banner), independent of
// whether the Supabase-backed printer list happens to have changed too.
export function subscribeMQTTConnection(onChange: () => void): () => void {
  return onMQTTStatusChanged(onChange)
}

export function getMQTTPrinterMetaByIndex(printerIndex: number): { online: boolean; busy: boolean; lastError: string | null } | null {
  const entry = cachedPrinterEntries[printerIndex]
  if (!entry) return null
  return { online: entry.online, busy: entry.busy, lastError: entry.lastError }
}

export function getMQTTConnectionState(): { connected: boolean; lastError: string | null } {
  return {
    connected: isMQTTConnected(),
    lastError: getMQTTLastError(),
  }
}

export function isDummyPrinter(printerName: string): boolean {
  return printerName === DUMMY_PRINTER_NAME
}

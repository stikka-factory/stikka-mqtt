import type {
  PrinterInfo,
  FontInfo,
  AppInfo,
  PrintStats,
  StaticModeConfig,
  MQTTFrontendConfig,
} from './types'
import {
  initMQTTTransport,
  waitForInitialDiscovery,
  getDiscoveredPrinters,
  publishImageCommand,
  publishBase64PNGCommand,
  publishZPLCommand,
  onMQTTStatusChanged,
  getDiscoveredPrinterMeta,
  isMQTTConnected,
  getMQTTLastError,
  getRemoteFonts,
  waitForSharedFonts,
  publishSharedFonts,
} from './mqtt-client'
import { imageDataURLToBase64PNG, imageDataURLToZPL } from './zpl-image'

let fallbackPrinters: PrinterInfo[] = []
let fallbackAppInfo: AppInfo | null = null
let mqttRuntimeConfig: MQTTFrontendConfig | null = null
let sharedFonts: FontInfo[] = []

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
// Variables/Secrets) is the only source for app.*/mqtt.* settings -- there's
// no in-app editor for them, so changing a deployment's config means
// changing repo Variables/Secrets and redeploying (see CLAUDE.md). Fonts are
// the one thing that stays runtime-editable and globally shared, via a
// broker-retained topic -- see applyRemoteFonts()/publishFont() below.
export async function initTransport(config: StaticModeConfig): Promise<void> {
  if (config.mode !== 'mqtt') {
    throw new Error('This fork supports only mqtt mode.')
  }
  if (!config.mqtt?.brokerURL) {
    throw new Error('Missing mqtt.brokerURL in config.json')
  }

  fallbackPrinters = [dummyPrinter()]
  fallbackAppInfo = config.app

  mqttRuntimeConfig = { ...config.mqtt }
  await initMQTTTransport(mqttRuntimeConfig)
  await waitForInitialDiscovery(mqttRuntimeConfig.discoveryWaitMs ?? 1500)

  await waitForSharedFonts(mqttRuntimeConfig.discoveryWaitMs ?? 1500)
  applyRemoteFonts()
}

function applyRemoteFonts(): void {
  const remote = getRemoteFonts()
  if (remote) sharedFonts = remote
}

function mqttPrinters(): PrinterInfo[] {
  const discovered = getDiscoveredPrinters()
  if (discovered.length > 0) return discovered
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

  // Fonts uploaded via the Settings tab are retained on the broker
  // (sharedFonts, refreshed by applyRemoteFonts()) so they're available to
  // every browser, not just the one that uploaded them. They win over a
  // built-in font of the same name.
  return [...builtIn.filter(f => !sharedFonts.some(s => s.name === f.name)), ...sharedFonts]
}

// Publishes a font (added to whatever's already shared) so every connected
// browser picks it up, instead of it staying local to the uploader.
export async function publishFont(font: FontInfo): Promise<void> {
  sharedFonts = [...sharedFonts.filter(f => f.name !== font.name), font]
  await publishSharedFonts(sharedFonts)
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

export async function fetchReadme(): Promise<string> {
  return 'Static MQTT mode is active. Configure printers on each ESP32 device UI. Topics: /<printername>/status/ and /<printername>/command/.'
}

export function subscribeMQTTPrinters(onChange: (printers: PrinterInfo[]) => void): () => void {
  return onMQTTStatusChanged(() => {
    onChange(mqttPrinters())
  })
}

export function getMQTTPrinterMetaByIndex(printerIndex: number): { online: boolean; busy: boolean; lastError: string | null } | null {
  const printers = mqttPrinters()
  const selected = printers[printerIndex]
  if (!selected) return null
  return getDiscoveredPrinterMeta(selected.name)
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

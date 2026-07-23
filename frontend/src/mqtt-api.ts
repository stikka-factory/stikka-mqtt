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
  updateMQTTTransport,
  waitForInitialDiscovery,
  getDiscoveredPrinters,
  publishImageCommand,
  publishBase64PNGCommand,
  publishZPLCommand,
  onMQTTStatusChanged,
  getDiscoveredPrinterMeta,
  isMQTTConnected,
  getMQTTLastError,
  getRemoteAppConfig,
  waitForSharedAppConfig,
  publishSharedAppConfig,
} from './mqtt-client'
import {
  saveMQTTOverride,
  clearMQTTOverride,
  saveStaticConfigOverride,
  clearStaticConfigOverride,
} from './static-config'
import { imageDataURLToBase64PNG, imageDataURLToZPL } from './zpl-image'

let fallbackPrinters: PrinterInfo[] = []
let fallbackAppInfo: AppInfo | null = null
let mqttRuntimeConfig: MQTTFrontendConfig | null = null
let staticRuntimeConfig: StaticModeConfig | null = null

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

export async function initTransport(config: StaticModeConfig): Promise<void> {
  if (config.mode !== 'mqtt') {
    throw new Error('This fork supports only mqtt mode.')
  }
  if (!config.mqtt?.brokerURL) {
    throw new Error('Missing mqtt.brokerURL in config.json')
  }

  staticRuntimeConfig = {
    ...config,
    app: { ...config.app },
    mqtt: { ...config.mqtt },
  }

  fallbackPrinters = [dummyPrinter()]
  fallbackAppInfo = config.app

  mqttRuntimeConfig = { ...config.mqtt }
  await initMQTTTransport(mqttRuntimeConfig)
  await waitForInitialDiscovery(mqttRuntimeConfig.discoveryWaitMs ?? 1500)

  // App-level settings saved from the Settings tab are retained on the
  // broker so every browser picks them up here, instead of only the one
  // that saved them (which used to be the only place localStorage kept it).
  await waitForSharedAppConfig(mqttRuntimeConfig.discoveryWaitMs ?? 1500)
  applyRemoteAppConfig()
}

function applyRemoteAppConfig(): void {
  const remote = getRemoteAppConfig()
  if (!remote || !staticRuntimeConfig) return
  staticRuntimeConfig.app = {
    name: remote.name,
    subtitle: remote.subtitle,
    zplExample: remote.zplExample,
    zplRawEnabled: remote.zplRawEnabled,
    cableLabelEnabled: remote.cableLabelEnabled,
    cableLabelZPLTemplate: remote.cableLabelZPLTemplate,
  }
  staticRuntimeConfig.mqttSettingsPassword = remote.mqttSettingsPassword
  fallbackAppInfo = staticRuntimeConfig.app
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
  try {
    const res = await fetch(indexURL, { cache: 'no-store' })
    if (!res.ok) return []
    const data = await res.json() as { fonts?: Array<{ name: string; path: string }> }
    return (data.fonts ?? []).map(f => ({
      name: f.name,
      path: `${import.meta.env.BASE_URL}fonts/${f.path}`,
    }))
  } catch {
    return []
  }
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

export async function fetchRandomImage(kind: 'cat' | 'dog' | 'dino'): Promise<string> {
  if (kind === 'cat') {
    const catRes = await fetch('https://api.thecatapi.com/v1/images/search')
    if (!catRes.ok) throw new Error(`Fetch cat metadata failed: ${catRes.status}`)
    const catData = await catRes.json() as Array<{ url?: string }>
    const catURL = catData?.[0]?.url
    if (!catURL) throw new Error('Cat API returned no image URL')
    return catURL
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
  return dinoURL
}

export function getMQTTConfig(): MQTTFrontendConfig | null {
  if (!mqttRuntimeConfig) return null
  return { ...mqttRuntimeConfig }
}

export async function updateMQTTConfig(next: MQTTFrontendConfig): Promise<void> {
  mqttRuntimeConfig = { ...next }
  saveMQTTOverride(mqttRuntimeConfig)
  await updateMQTTTransport(mqttRuntimeConfig)
  await waitForInitialDiscovery(mqttRuntimeConfig.discoveryWaitMs ?? 1500)
}

export async function resetMQTTConfig(defaultConfig: MQTTFrontendConfig): Promise<void> {
  clearMQTTOverride()
  mqttRuntimeConfig = { ...defaultConfig }
  await updateMQTTTransport(mqttRuntimeConfig)
  await waitForInitialDiscovery(mqttRuntimeConfig.discoveryWaitMs ?? 1500)
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

export function getStaticRuntimeConfig(): StaticModeConfig | null {
  if (!staticRuntimeConfig) return null
  return {
    ...staticRuntimeConfig,
    app: { ...staticRuntimeConfig.app },
    mqtt: { ...staticRuntimeConfig.mqtt },
  }
}

export async function updateStaticRuntimeConfig(next: StaticModeConfig): Promise<void> {
  const nextApp = { ...next.app }
  const nextSettingsPassword = next.mqttSettingsPassword

  staticRuntimeConfig = {
    ...next,
    app: { ...next.app },
    mqtt: { ...next.mqtt },
  }
  saveStaticConfigOverride(staticRuntimeConfig)
  await initTransport(staticRuntimeConfig)

  // initTransport() just applied whatever app config was previously
  // retained on the broker (possibly stale); what was just saved here wins,
  // and republishing makes it the new retained value for every other
  // browser that connects.
  staticRuntimeConfig.app = nextApp
  staticRuntimeConfig.mqttSettingsPassword = nextSettingsPassword
  fallbackAppInfo = nextApp
  await publishSharedAppConfig({ ...nextApp, mqttSettingsPassword: nextSettingsPassword })
}

export async function resetStaticRuntimeConfig(defaultConfig: StaticModeConfig): Promise<void> {
  clearStaticConfigOverride()
  staticRuntimeConfig = {
    ...defaultConfig,
    app: { ...defaultConfig.app },
    mqtt: { ...defaultConfig.mqtt },
  }
  await initTransport(staticRuntimeConfig)
}

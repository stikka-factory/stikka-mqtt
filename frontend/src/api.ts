import type {
  PrinterInfo,
  FontInfo,
  AppInfo,
  ScannedPrinter,
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
} from './mqtt-client'
import {
  saveMQTTOverride,
  clearMQTTOverride,
  saveStaticConfigOverride,
  clearStaticConfigOverride,
} from './static-config'
import { imageDataURLToBase64PNG, imageDataURLToZPL } from './zpl-image'

const BASE = ''
let transportMode: 'backend' | 'mqtt' = 'backend'
let fallbackPrinters: PrinterInfo[] = []
let fallbackFonts: FontInfo[] = []
let fallbackAppInfo: AppInfo | null = null
let mqttRuntimeConfig: MQTTFrontendConfig | null = null
let staticRuntimeConfig: StaticModeConfig | null = null

async function apiJSON<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const text = await res.text()
    // FastAPI error responses are JSON with a "detail" field
    try {
      const json = JSON.parse(text)
      const detail = json?.detail
      if (typeof detail === 'string') throw new Error(detail)
      if (Array.isArray(detail)) throw new Error(detail.map((d: { msg?: string }) => d.msg ?? String(d)).join('; '))
    } catch (e) {
      if (e instanceof SyntaxError) throw new Error(`${res.status} ${text.trim()}`)
      throw e
    }
  }
  return res.json()
}

export async function initTransport(config: StaticModeConfig | null): Promise<void> {
  staticRuntimeConfig = config ? { ...config, app: { ...config.app }, mqtt: config.mqtt ? { ...config.mqtt } : undefined, fonts: [...(config.fonts ?? [])], printers: [...(config.printers ?? [])] } : null

  if (!config || config.mode !== 'mqtt') {
    transportMode = 'backend'
    fallbackPrinters = []
    fallbackFonts = []
    fallbackAppInfo = null
    mqttRuntimeConfig = null
    return
  }

  transportMode = 'mqtt'
  fallbackPrinters = config.printers ?? []
  fallbackFonts = config.fonts ?? []
  fallbackAppInfo = config.app

  if (!config.mqtt) {
    throw new Error('Static mode requires an mqtt configuration in config.json')
  }

  mqttRuntimeConfig = { ...config.mqtt }
  await initMQTTTransport(mqttRuntimeConfig)
  await waitForInitialDiscovery(mqttRuntimeConfig.discoveryWaitMs ?? 1500)
}

export function isMQTTMode(): boolean {
  return transportMode === 'mqtt'
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
  if (transportMode === 'mqtt' && fallbackAppInfo) {
    return fallbackAppInfo
  }
  return apiJSON<AppInfo>('GET', '/api/appinfo')
}

export async function fetchPrinters(): Promise<PrinterInfo[]> {
  if (transportMode === 'mqtt') {
    return mqttPrinters()
  }
  return apiJSON<PrinterInfo[]>('GET', '/api/printers')
}

export async function fetchFonts(): Promise<FontInfo[]> {
  if (transportMode === 'mqtt') {
    return fallbackFonts
  }
  return apiJSON<FontInfo[]>('GET', '/api/fonts')
}

export async function printImage(printerIndex: number, imageDataURL: string): Promise<void> {
  if (transportMode === 'mqtt') {
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
      )
      await publishZPLCommand(printerName, zpl)
      return
    }

    await publishImageCommand(printerName, imageDataURL)
    return
  }
  await apiJSON<{ status: string }>('POST', '/api/print', {
    printerIndex,
    image: imageDataURL,
  })
}

export async function sendRawZPL(printerIndex: number, zpl: string): Promise<void> {
  if (transportMode === 'mqtt') {
    const printerName = pickPrinterName(printerIndex)
    await publishZPLCommand(printerName, zpl)
    return
  }
  await apiJSON<{ status: string }>('POST', '/api/zpl/raw', { printerIndex, zpl })
}

export async function previewZPL(printerIndex: number, zpl: string): Promise<string> {
  if (transportMode === 'mqtt') {
    throw new Error('ZPL preview is not available in static MQTT mode')
  }
  const res = await fetch(BASE + '/api/zpl/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ printerIndex, zpl }),
  })
  if (!res.ok) {
    throw new Error(`ZPL preview failed: ${res.status}`)
  }
  const blob = await res.blob()
  return URL.createObjectURL(blob)
}

export async function fetchRandomImage(kind: 'cat' | 'dog' | 'dino'): Promise<string> {
  if (transportMode === 'mqtt') {
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
  const res = await fetch(BASE + `/api/random/${kind}`)
  if (!res.ok) throw new Error(`Fetch ${kind} failed: ${res.status}`)
  const blob = await res.blob()
  return URL.createObjectURL(blob)
}

export async function fetchConfig(password: string): Promise<string> {
  const res = await fetch(BASE + '/api/config', {
    headers: { 'X-Config-Password': password },
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status} ${text.trim()}`)
  }
  return res.text()
}

export async function saveConfig(password: string, body: string): Promise<void> {
  const res = await fetch(BASE + '/api/config', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Config-Password': password,
    },
    body,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status} ${text.trim()}`)
  }
}

export function getMQTTConfig(): MQTTFrontendConfig | null {
  if (transportMode !== 'mqtt' || !mqttRuntimeConfig) return null
  return { ...mqttRuntimeConfig }
}

export async function updateMQTTConfig(next: MQTTFrontendConfig): Promise<void> {
  if (transportMode !== 'mqtt') {
    throw new Error('MQTT config can only be updated in static MQTT mode')
  }
  mqttRuntimeConfig = { ...next }
  saveMQTTOverride(mqttRuntimeConfig)
  await updateMQTTTransport(mqttRuntimeConfig)
  await waitForInitialDiscovery(mqttRuntimeConfig.discoveryWaitMs ?? 1500)
}

export async function resetMQTTConfig(defaultConfig: MQTTFrontendConfig): Promise<void> {
  if (transportMode !== 'mqtt') {
    throw new Error('MQTT config can only be reset in static MQTT mode')
  }
  clearMQTTOverride()
  mqttRuntimeConfig = { ...defaultConfig }
  await updateMQTTTransport(mqttRuntimeConfig)
  await waitForInitialDiscovery(mqttRuntimeConfig.discoveryWaitMs ?? 1500)
}

export async function fetchStats(): Promise<PrintStats> {
  if (transportMode === 'mqtt') {
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
  return apiJSON<PrintStats>('GET', '/api/stats')
}

export async function fetchReadme(): Promise<string> {
  if (transportMode === 'mqtt') {
    return 'Static MQTT mode is active. Configure printers on each ESP32 device UI and publish status to /status/<printername>.'
  }
  const res = await fetch(BASE + '/api/readme')
  if (!res.ok) throw new Error(`Fetch README failed: ${res.status}`)
  return res.text()
}

export async function scanPrinters(password: string): Promise<ScannedPrinter[]> {
  if (transportMode === 'mqtt') {
    throw new Error('Printer scanning is unavailable in static MQTT mode')
  }
  const res = await fetch(BASE + '/api/printers/scan', {
    headers: { 'X-Config-Password': password },
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status} ${text.trim()}`)
  }
  return res.json()
}

export async function uploadFonts(password: string, files: FileList): Promise<FontInfo[]> {
  if (transportMode === 'mqtt') {
    throw new Error('Font uploads are unavailable in static MQTT mode')
  }
  const form = new FormData()
  for (const f of Array.from(files)) form.append('files', f)
  const res = await fetch(BASE + '/api/fonts/upload', {
    method: 'POST',
    headers: { 'X-Config-Password': password },
    body: form,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status} ${text.trim()}`)
  }
  return res.json()
}

export async function uploadConfig(password: string, file: File): Promise<void> {
  if (transportMode === 'mqtt') {
    throw new Error('Config uploads are unavailable in static MQTT mode')
  }
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(BASE + '/api/config/upload', {
    method: 'POST',
    headers: { 'X-Config-Password': password },
    body: form,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status} ${text.trim()}`)
  }
}

export function subscribeMQTTPrinters(onChange: (printers: PrinterInfo[]) => void): () => void {
  if (transportMode !== 'mqtt') return () => {}
  return onMQTTStatusChanged(() => {
    onChange(mqttPrinters())
  })
}

export function getMQTTPrinterMetaByIndex(printerIndex: number): { online: boolean; busy: boolean; lastError: string | null } | null {
  if (transportMode !== 'mqtt') return null
  const printers = mqttPrinters()
  const selected = printers[printerIndex]
  if (!selected) return null
  return getDiscoveredPrinterMeta(selected.name)
}

export function getStaticRuntimeConfig(): StaticModeConfig | null {
  if (!staticRuntimeConfig) return null
  return {
    ...staticRuntimeConfig,
    app: { ...staticRuntimeConfig.app },
    mqtt: staticRuntimeConfig.mqtt ? { ...staticRuntimeConfig.mqtt } : undefined,
    fonts: [...(staticRuntimeConfig.fonts ?? [])],
    printers: [...(staticRuntimeConfig.printers ?? [])],
  }
}

export async function updateStaticRuntimeConfig(next: StaticModeConfig): Promise<void> {
  staticRuntimeConfig = {
    ...next,
    app: { ...next.app },
    mqtt: next.mqtt ? { ...next.mqtt } : undefined,
    fonts: [...(next.fonts ?? [])],
    printers: [...(next.printers ?? [])],
  }
  saveStaticConfigOverride(staticRuntimeConfig)
  await initTransport(staticRuntimeConfig)
}

export async function resetStaticRuntimeConfig(defaultConfig: StaticModeConfig): Promise<void> {
  clearStaticConfigOverride()
  staticRuntimeConfig = {
    ...defaultConfig,
    app: { ...defaultConfig.app },
    mqtt: defaultConfig.mqtt ? { ...defaultConfig.mqtt } : undefined,
    fonts: [...(defaultConfig.fonts ?? [])],
    printers: [...(defaultConfig.printers ?? [])],
  }
  await initTransport(staticRuntimeConfig)
}

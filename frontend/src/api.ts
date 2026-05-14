import type { PrinterInfo, FontInfo, AppInfo, ScannedPrinter, PrintStats } from './types'

const BASE = ''

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

export async function fetchAppInfo(): Promise<AppInfo> {
  return apiJSON<AppInfo>('GET', '/api/appinfo')
}

export async function fetchPrinters(): Promise<PrinterInfo[]> {
  return apiJSON<PrinterInfo[]>('GET', '/api/printers')
}

export async function fetchFonts(): Promise<FontInfo[]> {
  return apiJSON<FontInfo[]>('GET', '/api/fonts')
}

export async function printImage(printerIndex: number, imageDataURL: string): Promise<void> {
  await apiJSON<{ status: string }>('POST', '/api/print', {
    printerIndex,
    image: imageDataURL,
  })
}

export async function sendRawZPL(printerIndex: number, zpl: string): Promise<void> {
  await apiJSON<{ status: string }>('POST', '/api/zpl/raw', { printerIndex, zpl })
}

export async function previewZPL(printerIndex: number, zpl: string): Promise<string> {
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

export async function fetchStats(): Promise<PrintStats> {
  return apiJSON<PrintStats>('GET', '/api/stats')
}

export async function fetchReadme(): Promise<string> {
  const res = await fetch(BASE + '/api/readme')
  if (!res.ok) throw new Error(`Fetch README failed: ${res.status}`)
  return res.text()
}

export async function scanPrinters(password: string): Promise<ScannedPrinter[]> {
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

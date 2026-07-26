import { createClient, type SupabaseClient } from '@supabase/supabase-js'
import type { FontInfo, ImageSourceKind, PrinterInfo, PrinterStatusMessage, PrintStats, SupabaseFrontendConfig } from './types'

let client: SupabaseClient | null = null

export function initSupabaseTransport(cfg: SupabaseFrontendConfig): void {
  client = createClient(cfg.url, cfg.anonKey)
}

function requireClient(): SupabaseClient {
  if (!client) throw new Error('Supabase is not initialized')
  return client
}

// ── Fonts ────────────────────────────────────────────────────────────────

interface FontRow {
  name: string
  font_url: string
}

export async function fetchSupabaseFonts(): Promise<FontInfo[]> {
  const { data, error } = await requireClient().from('fonts').select('name, font_url').order('name')
  if (error) throw error
  return ((data ?? []) as FontRow[]).map(row => ({ name: row.name, path: row.font_url }))
}

// Suffix with a timestamp so re-uploading a font under the same display name
// doesn't collide with (or get blocked by) the previous object of that name.
function fontStorageKey(name: string, sourceFileName: string): string {
  const extMatch = /\.[^./]+$/.exec(sourceFileName)
  const extension = extMatch ? extMatch[0] : ''
  const safeName = name.replace(/[^a-zA-Z0-9_-]/g, '_')
  return `${safeName}-${Date.now()}${extension}`
}

export async function uploadSupabaseFont(name: string, file: File): Promise<FontInfo> {
  const sb = requireClient()
  const key = fontStorageKey(name, file.name)

  const { error: uploadError } = await sb.storage.from('fonts').upload(key, file, {
    contentType: file.type || 'font/ttf',
  })
  if (uploadError) throw uploadError

  const { data: publicUrlData } = sb.storage.from('fonts').getPublicUrl(key)
  const fontURL = publicUrlData.publicUrl

  const { error: upsertError } = await sb.from('fonts').upsert({ name, font_url: fontURL })
  if (upsertError) throw upsertError

  return { name, path: fontURL }
}

export function subscribeSupabaseFonts(onChange: () => void): () => void {
  const sb = requireClient()
  const channel = sb
    .channel('fonts-changes')
    .on('postgres_changes', { event: '*', schema: 'public', table: 'fonts' }, onChange)
    .subscribe()
  return () => { void sb.removeChannel(channel) }
}

// ── Print statistics ─────────────────────────────────────────────────────

const STATS_ROW_ID = 1

export async function fetchSupabaseStats(): Promise<PrintStats> {
  const { data, error } = await requireClient()
    .from('print_stats')
    .select('printed_total, printed_cats, printed_dogs, printed_dinos, printed_uploaded_images, printed_webcam_images, printed_without_image')
    .eq('id', STATS_ROW_ID)
    .single()
  if (error) throw error
  return data as PrintStats
}

// Atomic server-side increment (record_print() in supabase/schema.sql) --
// unlike the old MQTT-retained approach, concurrent prints from different
// browsers can no longer race and undercount.
export async function recordSupabasePrint(kind: ImageSourceKind): Promise<void> {
  const { error } = await requireClient().rpc('record_print', { kind })
  if (error) throw error
}

export function subscribeSupabaseStats(onChange: () => void): () => void {
  const sb = requireClient()
  const channel = sb
    .channel('print-stats-changes')
    .on('postgres_changes', { event: '*', schema: 'public', table: 'print_stats' }, onChange)
    .subscribe()
  return () => { void sb.removeChannel(channel) }
}

// ── Discovered printer nodes ─────────────────────────────────────────────

export interface SupabasePrinterEntry {
  printer: PrinterInfo
  online: boolean
  busy: boolean
  lastError: string | null
}

interface PrinterRow {
  name: string
  type: string
  dpi: number
  serial: string
  label_width: number
  label_length: number
  label_is_round: boolean
  label_vertical_offset: number
  label_cut: boolean
  zpl_compression_supported: boolean
  online: boolean
  busy: boolean
  last_error: string | null
}

// A node that loses power or Wi-Fi never gets to publish an "offline"
// status -- it just stops. This is a real server-side wall-clock cutoff
// (unlike the old client-side timer), so it's consistent across every
// browser and unaffected by any single browser reloading.
const NODE_TIMEOUT_MS = 5 * 60 * 1000

export async function fetchSupabasePrinters(): Promise<SupabasePrinterEntry[]> {
  const cutoff = new Date(Date.now() - NODE_TIMEOUT_MS).toISOString()
  const { data, error } = await requireClient()
    .from('printers')
    .select('name, type, dpi, serial, label_width, label_length, label_is_round, label_vertical_offset, label_cut, zpl_compression_supported, online, busy, last_error')
    .gt('last_seen', cutoff)
    .order('name')
  if (error) throw error
  return ((data ?? []) as PrinterRow[]).map((row, index) => ({
    printer: {
      index,
      name: row.name,
      serial: row.serial,
      type: row.type,
      dpi: row.dpi,
      label: {
        width: row.label_width,
        length: row.label_length,
        isRound: row.label_is_round,
        verticalOffset: row.label_vertical_offset,
        cut: row.label_cut,
      },
      zplCompressionSupported: row.zpl_compression_supported,
    },
    online: row.online,
    busy: row.busy,
    lastError: row.last_error,
  }))
}

// Best-effort: called from mqtt-client.ts for every full status snapshot
// received from the broker. A failed upsert (offline, RLS misconfigured,
// etc.) just means this browser didn't manage to relay this one status
// update -- it's not this browser's own printer list, so there's nothing
// useful to surface to its user beyond a console warning.
//
// isRetainedReplay: the ESP32 always publishes its status retained (see
// publishStatus() in mqtt_bridge.cpp), including its periodic heartbeat --
// it has no MQTT last-will, so a device that dies (power/Wi-Fi loss, or a
// rename that abandons its old topic) leaves that retained message on the
// broker forever. Per MQTT 3.3.1-8/-9, the broker only sets RETAIN=1 on a
// delivered PUBLISH when it's replaying a stored message to a *new*
// subscription; a live message forwarded to an already-subscribed client
// always arrives with RETAIN=0, regardless of how the publisher sent it.
// So a retained delivery here means "this is whatever was last on the
// topic," not "this printer is alive right now" -- bumping last_seen for it
// would let a long-dead printer's stale status get replayed (and its
// staleness clock reset) every time any browser subscribes, permanently
// defeating fetchSupabasePrinters()'s 5-minute cutoff. Omitting last_seen
// from the upsert leaves an existing row's last_seen untouched on conflict
// (PostgREST only updates columns present in the body) while still letting
// a brand-new printer appear immediately via its default now() value.
export async function upsertSupabasePrinter(name: string, message: PrinterStatusMessage, isRetainedReplay = false): Promise<void> {
  if (!client) return
  const label = message.capabilities?.label ?? message.label ?? {}
  const row: Record<string, unknown> = {
    name,
    type: message.capabilities?.type ?? message.type ?? 'zpl',
    dpi: message.capabilities?.dpi ?? message.dpi ?? 203,
    serial: message.serial ?? '',
    label_width: label.width ?? 80,
    label_length: label.length ?? 80,
    label_is_round: label.isRound ?? false,
    label_vertical_offset: label.verticalOffset ?? 0,
    label_cut: label.cut ?? false,
    zpl_compression_supported: message.capabilities?.zplCompression ?? false,
    online: message.online ?? true,
    busy: message.busy ?? false,
    last_error: message.last_error ?? null,
  }
  if (!isRetainedReplay) {
    row.last_seen = new Date().toISOString()
  }
  const { error } = await client.from('printers').upsert(row)
  if (error) console.warn('Could not upsert printer status to Supabase:', error)
}

export function subscribeSupabasePrinters(onChange: () => void): () => void {
  const sb = requireClient()
  const channel = sb
    .channel('printers-changes')
    .on('postgres_changes', { event: '*', schema: 'public', table: 'printers' }, onChange)
    .subscribe()
  return () => { void sb.removeChannel(channel) }
}

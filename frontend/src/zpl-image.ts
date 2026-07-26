function decodeDataURL(dataURL: string): { mime: string; base64: string } {
  const match = dataURL.match(/^data:([^;]+);base64,(.+)$/)
  if (!match) {
    throw new Error('Expected a base64 data URL')
  }
  return {
    mime: match[1],
    base64: match[2],
  }
}

async function loadImageFromDataURL(dataURL: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error('Could not decode image'))
    img.src = dataURL
  })
}

function thresholdToMonoBytes(canvas: HTMLCanvasElement): { bytesPerRow: number; bytes: Uint8Array } {
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Could not create canvas context')

  const { width, height } = canvas
  const img = ctx.getImageData(0, 0, width, height)
  const d = img.data
  const bytesPerRow = Math.ceil(width / 8)
  const out = new Uint8Array(bytesPerRow * height)

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const p = (y * width + x) * 4
      const gray = 0.299 * d[p] + 0.587 * d[p + 1] + 0.114 * d[p + 2]
      const isBlack = gray < 128
      if (isBlack) {
        const bi = y * bytesPerRow + (x >> 3)
        const mask = 0x80 >> (x & 7)
        out[bi] |= mask
      }
    }
  }

  return { bytesPerRow, bytes: out }
}

function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes)
    .map(v => v.toString(16).padStart(2, '0').toUpperCase())
    .join('')
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = ''
  const chunkSize = 0x8000
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize))
  }
  return btoa(binary)
}

async function deflateZlib(bytes: Uint8Array): Promise<Uint8Array> {
  const stream = new Blob([bytes.slice().buffer]).stream().pipeThrough(new CompressionStream('deflate'))
  const buffer = await new Response(stream).arrayBuffer()
  return new Uint8Array(buffer)
}

// CRC-16/XMODEM (poly 0x1021, init 0x0000, MSB-first, no reflection, no
// final XOR) computed over the *base64 text* -- verified byte-for-byte
// against a real Z64-compressed ZPL sample from a third-party converter
// that a real printer accepted. The earlier reflected CRC-16-CCITT variant
// (poly 0x8408/init 0xFFFF/complement+byteswap, modeled on the zebrafy
// library) produced a different value for the same input and was silently
// rejected on real hardware -- a CRC mismatch aborts the ^GF download with
// no error on the wire, indistinguishable from the printer not supporting
// :Z64:/:B64: at all. Not every printer supports this framing regardless,
// which is why it's opt-in per printer via the `compressionSupported`
// capability flag, not assumed.
function crc16CCITT(bytes: Uint8Array): number {
  let crc = 0x0000
  for (let i = 0; i < bytes.length; i++) {
    crc ^= bytes[i] << 8
    for (let b = 0; b < 8; b++) {
      crc = (crc & 0x8000) ? ((crc << 1) ^ 0x1021) & 0xffff : (crc << 1) & 0xffff
    }
  }
  return crc & 0xffff
}

function crcHex4(n: number): string {
  return n.toString(16).toUpperCase().padStart(4, '0')
}

// Returns both the ^GF data-string parameter and the byte-count (b) value
// that should go with it. For compressed (:Z64:) fields, byte-count is set
// equal to the uncompressed graphic-field count (c) rather than the actual
// transmitted string length -- matching a real Z64 sample (from a
// third-party converter) that a real printer accepted. The printer likely
// doesn't use byte-count to delimit compressed data at all (it relies on
// the self-terminating ":...:CRC" structure instead), so this mirrors what
// working encoders do rather than a value confirmed to be independently
// load-bearing.
async function buildGraphicField(
  monoBytes: Uint8Array,
  compressionSupported: boolean,
): Promise<{ dataString: string; binaryByteCount: number }> {
  if (!compressionSupported || typeof CompressionStream === 'undefined') {
    const dataString = bytesToHex(monoBytes)
    return { dataString, binaryByteCount: dataString.length }
  }
  const compressed = await deflateZlib(monoBytes)
  const b64 = bytesToBase64(compressed)
  const b64Bytes = new TextEncoder().encode(b64)
  const crc = crcHex4(crc16CCITT(b64Bytes))
  return { dataString: `:Z64:${b64}:${crc}`, binaryByteCount: monoBytes.length }
}

export async function imageDataURLToZPL(
  dataURL: string,
  dpi: number,
  labelWidthMm: number,
  labelLengthMm: number,
  verticalOffsetMm = 0,
  compressionSupported = false,
): Promise<string> {
  const decoded = decodeDataURL(dataURL)
  if (!decoded.mime.startsWith('image/')) {
    throw new Error('Payload is not an image data URL')
  }

  const src = await loadImageFromDataURL(dataURL)

  const widthPx = Math.max(1, Math.round((labelWidthMm / 25.4) * dpi))
  const fallbackHeightPx = Math.max(1, Math.round((src.naturalHeight / src.naturalWidth) * widthPx))
  const contentHeightPx = labelLengthMm > 0
    ? Math.max(1, Math.round((labelLengthMm / 25.4) * dpi))
    : fallbackHeightPx

  // Continuous/endless media has no die-cut length calibrated on the printer
  // to align to, so content can otherwise print flush against the tear-off
  // line with no margin to cut by. A fixed 3mm quiet zone is added top and
  // bottom in that case; fixed-length (gap-sensed/die-cut) media keeps its
  // existing behavior of filling the full calibrated length.
  const endlessBorderMm = 3
  const borderPx = labelLengthMm > 0 ? 0 : Math.round((endlessBorderMm / 25.4) * dpi)
  const heightPx = contentHeightPx + borderPx * 2

  const canvas = document.createElement('canvas')
  canvas.width = widthPx
  canvas.height = heightPx

  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Could not create canvas context')
  ctx.fillStyle = '#FFFFFF'
  ctx.fillRect(0, 0, widthPx, heightPx)
  ctx.drawImage(src, 0, borderPx, widthPx, contentHeightPx)

  const { bytesPerRow, bytes: monoBytes } = thresholdToMonoBytes(canvas)
  const yOffsetDots = Math.max(0, Math.round((verticalOffsetMm / 25.4) * dpi))

  const graphicFieldCount = monoBytes.length
  const { dataString, binaryByteCount } = await buildGraphicField(monoBytes, compressionSupported)

  // Deliberately no ^PW/^LL for fixed-length (gap-sensed/die-cut) media:
  // that label's width/length are already calibrated on the printer (front
  // panel / prior ^JU calibration), same as the working raw-ZPL example and
  // cable label template. Forcing an explicit ^PW/^LL that doesn't land on
  // the printer's exact calibrated dot count is a common cause of a silent
  // pause/reject on gap-sensed media -- nothing prints and nothing is
  // reported back over the raw socket, since there's no ack channel on
  // port 9100.
  //
  // Continuous/endless media (labelLengthMm <= 0) is the opposite case:
  // there's no die-cut length calibrated on the printer to preserve, so
  // without an explicit ^LL the printer falls back to whatever length was
  // last stored (unrelated to this job's actual content), printing at a
  // fixed length regardless of the image's real aspect ratio. So ^LL is
  // set explicitly here to match the dynamically computed heightPx.
  const header = labelLengthMm > 0 ? ['^XA'] : ['^XA', `^LL${heightPx}`]

  return [
    ...header,
    `^FO0,${yOffsetDots}`,
    `^GFA,${binaryByteCount},${graphicFieldCount},${bytesPerRow},${dataString}`,
    '^FS',
    '^XZ',
  ].join('\n')
}

export function imageDataURLToBase64PNG(dataURL: string): string {
  const decoded = decodeDataURL(dataURL)
  if (decoded.mime !== 'image/png') {
    throw new Error('Expected PNG data URL')
  }
  return decoded.base64
}

// ql_usb ESP32 bridges reassemble the whole base64 payload into one
// contiguous RAM buffer, then PNG-decode it into a second buffer of similar
// size -- both exist at once (mqtt_bridge.cpp), so on a ~320KB, no-PSRAM
// chip a payload much above this fails to allocate no matter how
// unfragmented the heap is. Label pixel dimensions come from printer.dpi
// (labelDimensions() in editor.ts), which can be misconfigured well above
// what the printhead can use -- this is a safety net independent of that,
// not a substitute for fixing the printer's configured dpi.
const MAX_QL_BASE64_BYTES = 60000
const MAX_DOWNSCALE_ATTEMPTS = 6

async function downscaleDataURL(dataURL: string, scale: number): Promise<string> {
  const img = await loadImageFromDataURL(dataURL)
  const w = Math.max(1, Math.round(img.naturalWidth * scale))
  const h = Math.max(1, Math.round(img.naturalHeight * scale))
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Could not create canvas context')
  ctx.drawImage(img, 0, 0, w, h)
  return canvas.toDataURL('image/png')
}

// Re-encodes at progressively lower resolution until the base64 payload
// fits MAX_QL_BASE64_BYTES. PNG byte size roughly tracks pixel area, so each
// attempt scales dimensions by sqrt(budget/actual) -- clamped so a single
// attempt can't stall (poorly-compressible, e.g. dithered, content) or
// overshoot into a blurry no-op-sized step.
export async function imageDataURLToBase64PNGCapped(dataURL: string): Promise<string> {
  let current = dataURL
  for (let attempt = 0; attempt < MAX_DOWNSCALE_ATTEMPTS; attempt++) {
    const base64 = imageDataURLToBase64PNG(current)
    if (base64.length <= MAX_QL_BASE64_BYTES) return base64
    const ratio = Math.sqrt(MAX_QL_BASE64_BYTES / base64.length)
    const scale = Math.min(0.9, Math.max(0.4, ratio))
    current = await downscaleDataURL(current, scale)
  }
  return imageDataURLToBase64PNG(current)
}

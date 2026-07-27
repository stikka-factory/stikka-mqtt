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

// ── Brother QL raster protocol (client-side) ────────────────────────────────
//
// Ported from esp32/src/targets/ql_raster.cpp, which used to do this same
// conversion on-device after decoding a PNG the frontend sent it. Doing it
// here instead means the wire payload is the final printer-ready raster
// stream: rowBytes x targetHeight + a small fixed header/footer, bounded and
// predictable from the label's physical dimensions alone -- completely
// independent of image content (photo vs text, dithered vs flat), unlike a
// PNG's size which is entirely at the mercy of how compressible the content
// happens to be. The ESP32 side becomes a pure byte-forwarder (targetSend()),
// same as the "zpl" protocol already was, and no longer needs PNGdec at all.
//
// Command byte sequence (order + values) is taken from the same reference
// implementation ql_raster.cpp cited (github.com/pklaus/brother_ql,
// raster.py/conversion.py). See that file's header comment for what this
// deliberately doesn't replicate (per-media offset table, real dithering,
// red/black, 600dpi, status read-back).

export interface QLRasterOptions {
  printheadPx: number      // 720 (standard family) or 1296 (QL-11xx wide)
  invalidateBytes: number  // 200 = most models, 400 = QL-800/810W/820NWB
  autoCut: boolean
  feedMarginDots: number
  rightMarginDots: number  // 0 = auto-center; >0 = distance from the head's right edge
  labelWidthMm: number
  labelLengthMm: number    // 0 = continuous/endless
}

function buildQLHeader(opts: QLRasterOptions, printheadPx: number, targetHeightPx: number): number[] {
  const out: number[] = []
  const switchRaster = [0x1b, 0x69, 0x61, 0x01] // ESC i a 1
  out.push(...switchRaster)

  let remaining = Math.max(0, opts.invalidateBytes)
  while (remaining > 0) {
    const n = Math.min(remaining, 32)
    for (let i = 0; i < n; i++) out.push(0x00)
    remaining -= n
  }

  out.push(0x1b, 0x40) // ESC @ (init)
  out.push(...switchRaster)

  // Media & quality (ESC i z). mtype 0x0A = continuous/endless tape, 0x0B =
  // die-cut label. valid_flags sets all three media fields plus high print
  // quality (bits 1/2/3/6).
  const continuous = opts.labelLengthMm <= 0
  const mtype = continuous ? 0x0a : 0x0b
  const mwidth = Math.round(opts.labelWidthMm) & 0xff
  const mlength = continuous ? 0x00 : Math.round(opts.labelLengthMm) & 0xff
  const rnumber = targetHeightPx >>> 0
  out.push(
    0x1b, 0x69, 0x7a, // ESC i z
    0x80 | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 6),
    mtype,
    mwidth,
    mlength,
    rnumber & 0xff,
    (rnumber >>> 8) & 0xff,
    (rnumber >>> 16) & 0xff,
    (rnumber >>> 24) & 0xff,
    0x00, // page 0 (single-page job)
    0x00,
  )

  if (opts.autoCut) {
    out.push(0x1b, 0x69, 0x4d, 0x40) // ESC i M, autocut on (bit 6)
    out.push(0x1b, 0x69, 0x41, 0x01) // ESC i A, cut every 1 label
  }

  // Expanded mode (ESC i K): cut_at_end mirrors autocut; 600dpi and
  // two-color printing aren't implemented, so both bits stay off.
  out.push(0x1b, 0x69, 0x4b, opts.autoCut ? (1 << 3) : 0x00)

  const feed = Math.max(0, opts.feedMarginDots) & 0xffff
  out.push(0x1b, 0x69, 0x64, feed & 0xff, (feed >>> 8) & 0xff) // ESC i d

  return out
}

// Nearest-neighbor resamples the source ImageData to targetWidthPx x
// targetHeightPx, thresholds each sampled pixel to black/white (gray < 128,
// matching the ESP32's former threshold), and bit-packs each row **mirrored**
// -- Brother's raster format expects lines flipped left-right (add_raster_data()
// in the reference raster.py flips before packing, rather than packing then
// reversing) -- at the offsetPx bit position, wrapped in a `0x67 0x00
// rowBytes` raster-line command per row.
function buildQLRasterRows(
  imgData: ImageData,
  targetWidthPx: number,
  targetHeightPx: number,
  offsetPx: number,
  printheadPx: number,
  rowBytes: number,
): number[] {
  const out: number[] = []
  const { width: srcWidth, height: srcHeight, data } = imgData
  const row = new Uint8Array(rowBytes)

  for (let ty = 0; ty < targetHeightPx; ty++) {
    const srcY = Math.min(srcHeight - 1, Math.floor((ty * srcHeight) / targetHeightPx))
    row.fill(0)

    for (let destX = 0; destX < targetWidthPx; destX++) {
      const srcX = Math.min(srcWidth - 1, Math.floor((destX * srcWidth) / targetWidthPx))
      const p = (srcY * srcWidth + srcX) * 4
      const gray = (299 * data[p] + 587 * data[p + 1] + 114 * data[p + 2]) / 1000
      if (gray < 128) {
        const bitPos = printheadPx - 1 - (offsetPx + destX)
        if (bitPos >= 0 && bitPos < printheadPx) {
          row[bitPos >> 3] |= 0x80 >> (bitPos & 7)
        }
      }
    }

    out.push(0x67, 0x00, rowBytes)
    for (let i = 0; i < rowBytes; i++) out.push(row[i])
  }

  return out
}

// Renders the label image at native 300dpi (Brother QL's fixed raster
// resolution, independent of whatever printer.dpi says -- same as the
// firmware never trusted a sent image's implied dpi either) and produces the
// complete printer-ready byte stream: header + one raster-line command per
// row + a single 0x1A (EOF) footer byte.
export async function imageDataURLToQLRasterBase64(dataURL: string, opts: QLRasterOptions): Promise<string> {
  const img = await loadImageFromDataURL(dataURL)
  const srcWidth = img.naturalWidth
  const srcHeight = img.naturalHeight
  const canvas = document.createElement('canvas')
  canvas.width = srcWidth
  canvas.height = srcHeight
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Could not create canvas context')
  ctx.drawImage(img, 0, 0)
  const imgData = ctx.getImageData(0, 0, srcWidth, srcHeight)

  const printheadPx = opts.printheadPx === 1296 ? 1296 : 720
  const rowBytes = printheadPx / 8

  const nativeDpi = 300
  let targetWidthPx = Math.max(1, Math.round((opts.labelWidthMm / 25.4) * nativeDpi))
  if (targetWidthPx > printheadPx) targetWidthPx = printheadPx
  const targetHeightPx = opts.labelLengthMm > 0
    ? Math.max(1, Math.round((opts.labelLengthMm / 25.4) * nativeDpi))
    : Math.max(1, Math.round((srcHeight / srcWidth) * targetWidthPx))

  const offsetPx = opts.rightMarginDots > 0
    ? Math.max(0, printheadPx - targetWidthPx - opts.rightMarginDots)
    : Math.floor((printheadPx - targetWidthPx) / 2)

  const header = buildQLHeader(opts, printheadPx, targetHeightPx)
  const rows = buildQLRasterRows(imgData, targetWidthPx, targetHeightPx, offsetPx, printheadPx, rowBytes)
  const footer = 0x1a // last page, EOF

  console.log(`[print] ql raster: src=${srcWidth}x${srcHeight} target=${targetWidthPx}x${targetHeightPx} printheadPx=${printheadPx} bytes=${header.length + rows.length + 1}`)

  return bytesToBase64(new Uint8Array([...header, ...rows, footer]))
}

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

function thresholdToMonoHex(canvas: HTMLCanvasElement): { totalBytes: number; bytesPerRow: number; hex: string } {
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

  const hex = Array.from(out)
    .map(v => v.toString(16).padStart(2, '0').toUpperCase())
    .join('')

  return {
    totalBytes: out.length,
    bytesPerRow,
    hex,
  }
}

export async function imageDataURLToZPL(
  dataURL: string,
  dpi: number,
  labelWidthMm: number,
  labelLengthMm: number,
  verticalOffsetMm = 0,
): Promise<string> {
  const decoded = decodeDataURL(dataURL)
  if (!decoded.mime.startsWith('image/')) {
    throw new Error('Payload is not an image data URL')
  }

  const src = await loadImageFromDataURL(dataURL)

  const widthPx = Math.max(1, Math.round((labelWidthMm / 25.4) * dpi))
  const fallbackHeightPx = Math.max(1, Math.round((src.naturalHeight / src.naturalWidth) * widthPx))
  const heightPx = labelLengthMm > 0
    ? Math.max(1, Math.round((labelLengthMm / 25.4) * dpi))
    : fallbackHeightPx

  const canvas = document.createElement('canvas')
  canvas.width = widthPx
  canvas.height = heightPx

  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Could not create canvas context')
  ctx.fillStyle = '#FFFFFF'
  ctx.fillRect(0, 0, widthPx, heightPx)
  ctx.drawImage(src, 0, 0, widthPx, heightPx)

  const { totalBytes, bytesPerRow, hex } = thresholdToMonoHex(canvas)
  const yOffsetDots = Math.max(0, Math.round((verticalOffsetMm / 25.4) * dpi))

  // Deliberately no ^PW/^LL: this label's width/length are already
  // calibrated on the printer (front panel / prior ^JU calibration), same
  // as the working raw-ZPL example and cable label template. Forcing an
  // explicit ^PW/^LL that doesn't land on the printer's exact calibrated
  // dot count is a common cause of a silent pause/reject on gap-sensed
  // media -- nothing prints and nothing is reported back over the raw
  // socket, since there's no ack channel on port 9100.
  return [
    '^XA',
    `^FO0,${yOffsetDots}`,
    `^GFA,${totalBytes},${totalBytes},${bytesPerRow},${hex}`,
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

/**
 * editor.ts — Canvas-based label rendering pipeline.
 *
 * All image processing runs entirely in the browser:
 *   source image → resize/crop → adjust levels → dither/comic → text overlay → barcode overlay → [circle mask]
 *
 * The finished canvas is returned to the caller who can display it as a preview
 * or send it to the Go server for printing.
 */

import * as bwipjs from 'bwip-js/browser'
import type { AppState, PrinterInfo, FontInfo } from './types'

// ── Font loading ─────────────────────────────────────────────────────────────

// Keyed by font name; stores the in-flight or completed load promise.
const fontLoadPromises = new Map<string, Promise<void>>()

export function loadFont(info: FontInfo): Promise<void> {
  if (!fontLoadPromises.has(info.name)) {
    const p = (async () => {
      const face = new FontFace(info.name, `url(${encodeURI(info.path)})`)
      await face.load()
      document.fonts.add(face)
    })().catch(() => {
      console.warn(`Could not load font "${info.name}" from ${info.path}`)
    })
    fontLoadPromises.set(info.name, p)
  }
  return fontLoadPromises.get(info.name)!
}

export async function loadAllFonts(fonts: FontInfo[]): Promise<void> {
  await Promise.all(fonts.map(loadFont))
}

// ── Image loading helper ─────────────────────────────────────────────────────

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => resolve(img)
    img.onerror = reject
    img.src = src
  })
}

// ── Canvas dimensions ────────────────────────────────────────────────────────

function labelDimensions(
  printer: PrinterInfo,
  srcW?: number,
  srcH?: number,
): { w: number; h: number } {
  const dpi = printer.dpi
  const widthPx = Math.round((printer.label.width / 25.4) * dpi)

  if (printer.label.length > 0) {
    return { w: widthPx, h: Math.round((printer.label.length / 25.4) * dpi) }
  }
  // Continuous label: derive height from source image aspect ratio
  if (srcW && srcH && srcW > 0) {
    return { w: widthPx, h: Math.round((srcH / srcW) * widthPx) }
  }
  // No image: square fallback
  return { w: widthPx, h: widthPx }
}

// ── Step 1: Draw source image onto canvas (resize / crop) ────────────────────

function drawSourceImage(
  ctx: CanvasRenderingContext2D,
  img: HTMLImageElement,
  canvasW: number,
  canvasH: number,
  crop: boolean,
  offsetX: number,
  offsetY: number,
): void {
  const srcRatio = img.naturalWidth / img.naturalHeight
  const dstRatio = canvasW / canvasH

  let sw: number, sh: number, sx: number, sy: number

  if (crop) {
    if (srcRatio > dstRatio) {
      sh = img.naturalHeight
      sw = sh * dstRatio
    } else {
      sw = img.naturalWidth
      sh = sw / dstRatio
    }
    sx = (img.naturalWidth - sw) / 2 + offsetX
    sy = (img.naturalHeight - sh) / 2 + offsetY
    sx = Math.max(0, Math.min(sx, img.naturalWidth - sw))
    sy = Math.max(0, Math.min(sy, img.naturalHeight - sh))
    ctx.drawImage(img, sx, sy, sw, sh, 0, 0, canvasW, canvasH)
  } else {
    // Letterbox
    let dw: number, dh: number
    if (srcRatio > dstRatio) {
      dw = canvasW
      dh = canvasW / srcRatio
    } else {
      dh = canvasH
      dw = canvasH * srcRatio
    }
    const dx = (canvasW - dw) / 2 + offsetX
    const dy = (canvasH - dh) / 2 + offsetY
    ctx.drawImage(img, dx, dy, dw, dh)
  }
}

// ── Step 2: Apply levels + contrast ─────────────────────────────────────────

function applyLevels(
  data: Uint8ClampedArray,
  blackPoint: number,
  whitePoint: number,
  contrast: number,
): void {
  const range = whitePoint - blackPoint || 1
  for (let i = 0; i < data.length; i += 4) {
    for (let c = 0; c < 3; c++) {
      let v = data[i + c]
      // Levels
      v = Math.max(0, Math.min(255, ((v - blackPoint) / range) * 255))
      // Contrast around midpoint 128
      if (contrast !== 1.0) {
        v = 128 + (v - 128) * contrast
        v = Math.max(0, Math.min(255, v))
      }
      data[i + c] = v
    }
  }
}

// ── Step 3a: Floyd–Steinberg dithering ──────────────────────────────────────

function floydSteinbergDither(
  data: Uint8ClampedArray,
  width: number,
  height: number,
): void {
  // Convert to grayscale float buffer
  const gray = new Float32Array(width * height)
  for (let i = 0; i < width * height; i++) {
    gray[i] = 0.299 * data[i * 4] + 0.587 * data[i * 4 + 1] + 0.114 * data[i * 4 + 2]
  }

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const idx = y * width + x
      const old = gray[idx]
      const newVal = old < 128 ? 0 : 255
      const err = old - newVal
      gray[idx] = newVal
      if (x + 1 < width) gray[idx + 1] += err * (7 / 16)
      if (y + 1 < height) {
        if (x > 0) gray[idx + width - 1] += err * (3 / 16)
        gray[idx + width] += err * (5 / 16)
        if (x + 1 < width) gray[idx + width + 1] += err * (1 / 16)
      }
    }
  }

  for (let i = 0; i < width * height; i++) {
    const v = gray[i] > 128 ? 255 : 0
    data[i * 4] = v
    data[i * 4 + 1] = v
    data[i * 4 + 2] = v
  }
}

// ── Step 3b: Comic / cel-shading filter ─────────────────────────────────────

function boxBlur(gray: Float32Array, width: number, height: number, radius: number): Float32Array {
  const out = new Float32Array(gray.length)
  const r = radius
  // Horizontal pass
  const tmp = new Float32Array(gray.length)
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      let sum = 0, count = 0
      for (let dx = -r; dx <= r; dx++) {
        const nx = x + dx
        if (nx >= 0 && nx < width) { sum += gray[y * width + nx]; count++ }
      }
      tmp[y * width + x] = sum / count
    }
  }
  // Vertical pass
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      let sum = 0, count = 0
      for (let dy = -r; dy <= r; dy++) {
        const ny = y + dy
        if (ny >= 0 && ny < height) { sum += tmp[ny * width + x]; count++ }
      }
      out[y * width + x] = sum / count
    }
  }
  return out
}

function comicFilter(
  data: Uint8ClampedArray,
  width: number,
  height: number,
  blackPoint: number,
): void {
  // 1. Grayscale
  const gray = new Float32Array(width * height)
  for (let i = 0; i < width * height; i++) {
    gray[i] = 0.299 * data[i * 4] + 0.587 * data[i * 4 + 1] + 0.114 * data[i * 4 + 2]
  }

  // 2. Blur
  const blurred = boxBlur(gray, width, height, 2)

  // 3. Posterize to 6 levels (0, 51, 102, 153, 204, 255)
  const posterized = new Float32Array(width * height)
  for (let i = 0; i < posterized.length; i++) {
    posterized[i] = Math.round(blurred[i] / 51) * 51
  }

  // 4. Edge detection (Sobel) on blurred
  const edgeThreshold = 5 + (blackPoint / 255) * 122
  const ink = new Uint8Array(width * height)
  for (let y = 1; y < height - 1; y++) {
    for (let x = 1; x < width - 1; x++) {
      const g = (py: number, px: number) => blurred[py * width + px]
      const gx = (
        -g(y - 1, x - 1) + g(y - 1, x + 1) +
        -2 * g(y, x - 1) + 2 * g(y, x + 1) +
        -g(y + 1, x - 1) + g(y + 1, x + 1)
      )
      const gy = (
        -g(y - 1, x - 1) - 2 * g(y - 1, x) - g(y - 1, x + 1) +
        g(y + 1, x - 1) + 2 * g(y + 1, x) + g(y + 1, x + 1)
      )
      const mag = Math.sqrt(gx * gx + gy * gy)
      ink[y * width + x] = mag >= edgeThreshold ? 1 : 0
    }
  }

  // 5. Composite: posterized tones + ink edges
  for (let i = 0; i < width * height; i++) {
    const v = ink[i] ? 0 : posterized[i]
    data[i * 4] = v
    data[i * 4 + 1] = v
    data[i * 4 + 2] = v
  }
}

// ── Step 4: Text overlay ─────────────────────────────────────────────────────

function wrapText(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string[] {
  const lines: string[] = []
  for (const paragraph of text.split('\n')) {
    const words = paragraph.split(' ').filter(Boolean)
    if (!words.length) { lines.push(''); continue }
    let current = words[0]
    for (const word of words.slice(1)) {
      const test = current + ' ' + word
      if (ctx.measureText(test).width <= maxWidth) {
        current = test
      } else {
        lines.push(current)
        current = word
      }
    }
    lines.push(current)
  }
  return lines
}

async function drawTextOverlay(
  ctx: CanvasRenderingContext2D,
  state: AppState,
): Promise<void> {
  const { text, fontName, textSize, hAlign, vAlign,
    textOffsetX, textOffsetY, rotateText, blackText, outline } = state
  if (!text.trim()) return

  const size = Math.max(5, textSize)
  const fontSpec = fontName ? `${size}px "${fontName}"` : `${size}px sans-serif`

  // Wait for the specific font's load promise to settle, then confirm it's
  // usable for canvas rendering via document.fonts.load().
  if (fontName) {
    const p = fontLoadPromises.get(fontName)
    if (p) await p
  }
  await document.fonts.load(fontSpec).catch(() => {})

  ctx.font = fontSpec

  const margin = 8
  const maxWidth = Math.max(20, ctx.canvas.width - margin * 2)
  const lines = wrapText(ctx, text.trim(), maxWidth)

  const lineSpacing = Math.max(2, size / 5)
  const lineMetrics = lines.map(l => ctx.measureText(l))
  const lineHeights = lineMetrics.map(m =>
    (m.actualBoundingBoxAscent ?? size) + (m.actualBoundingBoxDescent ?? size * 0.2)
  )
  const lineWidths = lineMetrics.map(m => m.width)
  const blockH = lineHeights.reduce((s, h) => s + h, 0) + lineSpacing * (lines.length - 1)
  const blockW = Math.max(...lineWidths, 1)

  const strokeW = outline ? Math.max(1, size / 12) : 0
  const pad = strokeW + 2

  // Render into a tight off-screen canvas so we can rotate it
  const textCanvas = document.createElement('canvas')
  textCanvas.width = blockW + pad * 2
  textCanvas.height = blockH + pad * 2
  const tc = textCanvas.getContext('2d')!
  tc.font = fontSpec
  tc.fillStyle = blackText ? '#000000' : '#ffffff'
  if (outline) {
    tc.strokeStyle = blackText ? '#ffffff' : '#000000'
    tc.lineWidth = strokeW * 2
    tc.lineJoin = 'round'
  }

  let y = pad
  for (let i = 0; i < lines.length; i++) {
    const lw = lineWidths[i]
    let x: number
    if (hAlign === 'Left') x = pad
    else if (hAlign === 'Right') x = pad + blockW - lw
    else x = pad + (blockW - lw) / 2
    // Draw baseline-aligned
    const baseline = y + lineHeights[i] - (lineMetrics[i].actualBoundingBoxDescent ?? size * 0.2)
    if (outline) tc.strokeText(lines[i], x, baseline)
    tc.fillText(lines[i], x, baseline)
    y += lineHeights[i] + lineSpacing
  }

  // Rotate if needed
  let rotated: HTMLCanvasElement | OffscreenCanvas = textCanvas
  const angle = (rotateText % 360 + 360) % 360
  if (angle !== 0) {
    const rad = (angle * Math.PI) / 180
    const cos = Math.abs(Math.cos(rad))
    const sin = Math.abs(Math.sin(rad))
    const rw = Math.round(textCanvas.width * cos + textCanvas.height * sin)
    const rh = Math.round(textCanvas.width * sin + textCanvas.height * cos)
    const rc = new OffscreenCanvas(rw, rh)
    const rx = rc.getContext('2d')!
    rx.translate(rw / 2, rh / 2)
    rx.rotate(rad)
    rx.drawImage(textCanvas, -textCanvas.width / 2, -textCanvas.height / 2)
    rotated = rc
  }

  const rw = rotated.width
  const rh = rotated.height

  // Position on main canvas
  let baseX: number, baseY: number
  if (hAlign === 'Left') baseX = 10
  else if (hAlign === 'Right') baseX = ctx.canvas.width - rw - 10
  else baseX = (ctx.canvas.width - rw) / 2

  if (vAlign === 'Top') baseY = 10
  else if (vAlign === 'Bottom') baseY = ctx.canvas.height - rh - 10
  else baseY = (ctx.canvas.height - rh) / 2

  ctx.drawImage(rotated as HTMLCanvasElement, baseX + textOffsetX, baseY + textOffsetY)
}

// ── Step 5: Barcode overlay ──────────────────────────────────────────────────

export function generateBarcodeCanvas(
  data: string,
  type: 'QR' | 'Code128' | 'Aztec' | 'DataMatrix',
  showText: boolean,
): HTMLCanvasElement {
  const typeMap: Record<string, string> = {
    QR: 'qrcode',
    Code128: 'code128',
    Aztec: 'azteccode',
    DataMatrix: 'datamatrix',
  }
  const canvas = document.createElement('canvas')
  bwipjs.toCanvas(canvas, {
    bcid: typeMap[type] || 'qrcode',
    text: data,
    scale: 3,
    includetext: showText && type === 'Code128',
    textxalign: 'center',
  })
  return canvas
}

function drawBarcodeOverlay(
  ctx: CanvasRenderingContext2D,
  state: AppState,
): void {
  const { barcodeCanvas, barcodeSize, barcodeOffsetX, barcodeOffsetY,
    barcodeRotate, barcodeHAlign, barcodeVAlign } = state
  if (!barcodeCanvas) return

  const size = Math.max(1, barcodeSize)
  const sw = barcodeCanvas.width * size
  const sh = barcodeCanvas.height * size

  // Scale
  const scaled = new OffscreenCanvas(sw, sh)
  const sc = scaled.getContext('2d') as OffscreenCanvasRenderingContext2D
  sc.imageSmoothingEnabled = false
  sc.drawImage(barcodeCanvas, 0, 0, sw, sh)

  // Rotate
  const angle = (barcodeRotate % 360 + 360) % 360
  let rotated: OffscreenCanvas | HTMLCanvasElement = scaled
  if (angle !== 0) {
    const rad = (angle * Math.PI) / 180
    const cos = Math.abs(Math.cos(rad))
    const sin = Math.abs(Math.sin(rad))
    const rw = Math.round(sw * cos + sh * sin)
    const rh = Math.round(sw * sin + sh * cos)
    const rc = new OffscreenCanvas(rw, rh)
    const rx = rc.getContext('2d') as OffscreenCanvasRenderingContext2D
    rx.fillStyle = '#ffffff'
    rx.fillRect(0, 0, rw, rh)
    rx.translate(rw / 2, rh / 2)
    rx.rotate(rad)
    rx.drawImage(scaled, -sw / 2, -sh / 2)
    rotated = rc
  }

  // Padding
  const padding = Math.max(4, size * 4)
  const padded = new OffscreenCanvas(rotated.width + padding * 2, rotated.height + padding * 2)
  const pc = padded.getContext('2d') as OffscreenCanvasRenderingContext2D
  pc.fillStyle = '#ffffff'
  pc.fillRect(0, 0, padded.width, padded.height)
  pc.drawImage(rotated as unknown as HTMLCanvasElement, padding, padding)

  const pw = padded.width
  const ph = padded.height

  let baseX: number
  if (barcodeHAlign === 'Left') baseX = 10
  else if (barcodeHAlign === 'Right') baseX = ctx.canvas.width - pw - 10
  else baseX = (ctx.canvas.width - pw) / 2

  let baseY: number
  if (barcodeVAlign === 'Top') baseY = 10
  else if (barcodeVAlign === 'Bottom') baseY = ctx.canvas.height - ph - 10
  else baseY = (ctx.canvas.height - ph) / 2

  ctx.drawImage(padded as unknown as HTMLCanvasElement, baseX + barcodeOffsetX, baseY + barcodeOffsetY)
}

// ── Step 6: Circular mask ────────────────────────────────────────────────────

function applyCircularMask(ctx: CanvasRenderingContext2D): void {
  const { width, height } = ctx.canvas
  const d = Math.min(width, height)
  const cx = width / 2, cy = height / 2

  // Save current pixels
  const data = ctx.getImageData(0, 0, width, height)
  ctx.clearRect(0, 0, width, height)

  // Draw white background
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, width, height)

  // Clip to circle and redraw
  ctx.save()
  ctx.beginPath()
  ctx.arc(cx, cy, d / 2, 0, Math.PI * 2)
  ctx.clip()
  ctx.putImageData(data, 0, 0)
  ctx.restore()
}

// ── Main render function ─────────────────────────────────────────────────────

export async function renderLabel(
  state: AppState,
  printer: PrinterInfo,
): Promise<HTMLCanvasElement> {
  // Load source image (if any)
  let srcImg: HTMLImageElement | null = null
  if (state.sourceImageURL) {
    try { srcImg = await loadImage(state.sourceImageURL) } catch { /* ignore */ }
  }

  const { w, h } = labelDimensions(
    printer,
    srcImg?.naturalWidth,
    srcImg?.naturalHeight,
  )

  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')!

  // White background
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, w, h)

  // Draw source image
  if (srcImg) {
    drawSourceImage(ctx, srcImg, w, h, state.cropImage, state.imgOffsetX, state.imgOffsetY)
  }

  // Apply pixel-level adjustments
  const imgData = ctx.getImageData(0, 0, w, h)
  const { data } = imgData

  if (state.comicFilter) {
    applyLevels(data, 0, 255, state.contrast)   // contrast only before comic
    comicFilter(data, w, h, state.blackPoint)
    if (state.ditherPreview) {
      floydSteinbergDither(data, w, h)
    }
  } else {
    applyLevels(data, state.blackPoint, state.whitePoint, state.contrast)
    if (state.ditherPreview) {
      floydSteinbergDither(data, w, h)
    }
  }
  ctx.putImageData(imgData, 0, 0)

  // Text overlay
  if (state.text.trim()) {
    await drawTextOverlay(ctx, state)
  }

  // Barcode overlay
  if (state.barcodeCanvas) {
    drawBarcodeOverlay(ctx, state)
  }

  // Circular mask for round labels
  if (printer.label.isRound) {
    applyCircularMask(ctx)
  }

  return canvas
}

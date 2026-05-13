/**
 * ui.ts — Builds and wires the entire Gostikka UI.
 *
 * No external framework — plain DOM manipulation with TypeScript.
 */

import type { AppState, PrinterInfo } from './types'
import { renderLabel, generateBarcodeCanvas, loadAllFonts } from './editor'
import * as api from './api'
import { marked } from 'marked'
import { EditorView, basicSetup } from 'codemirror'
import { EditorState } from '@codemirror/state'
import { json } from '@codemirror/lang-json'

// ── State ────────────────────────────────────────────────────────────────────

let state: AppState

// ── Debounced preview update ─────────────────────────────────────────────────

let previewTimer: number | null = null
let previewCanvas: HTMLCanvasElement | null = null
let previewRendering = false

function schedulePreview(): void {
  if (previewTimer !== null) clearTimeout(previewTimer)
  previewTimer = window.setTimeout(() => updatePreview(), 300)
}

async function updatePreview(): Promise<void> {
  if (!previewCanvas) return
  const printer = state.printers[state.selectedPrinterIndex]
  if (!printer) {
    const ctx = previewCanvas.getContext('2d')!
    ctx.clearRect(0, 0, previewCanvas.width, previewCanvas.height)
    return
  }

  if (previewRendering) return
  previewRendering = true
  try {
    const rendered = await renderLabel(state, printer)
    if (previewCanvas) {
      previewCanvas.width = rendered.width
      previewCanvas.height = rendered.height
      previewCanvas.getContext('2d')!.drawImage(rendered, 0, 0)
    }
  } catch (e) {
    console.error('Preview render error:', e)
  } finally {
    previewRendering = false
  }
}

// ── Utility DOM builders ──────────────────────────────────────────────────────

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Partial<HTMLElementTagNameMap[K]> & { [k: string]: unknown } = {},
  ...children: (Node | string)[]
): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag)
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') (e as HTMLElement).className = v as string
    else if (k === 'style') Object.assign((e as HTMLElement).style, v)
    else (e as HTMLElement).setAttribute(k, String(v))
  }
  for (const c of children) {
    e.append(typeof c === 'string' ? document.createTextNode(c) : c)
  }
  return e
}

function slider(
  label: string,
  min: number, max: number, step: number, value: number,
  onChange: (v: number) => void,
): HTMLElement {
  const id = 'slider-' + Math.random().toString(36).slice(2)
  const valDisplay = el('span', { class: 'slider-value' }, String(value))
  const input = el('input', { type: 'range', min: String(min), max: String(max), step: String(step), value: String(value), id })
  input.addEventListener('input', () => {
    const v = parseFloat(input.value)
    valDisplay.textContent = String(v)
    onChange(v)
  })
  const row = el('div', { class: 'slider-row' },
    el('label', { for: id, class: 'slider-label' }, label),
    input,
    valDisplay,
  )
  return row
}

function resetSlider(row: HTMLElement, value: number): void {
  const input = row.querySelector('input') as HTMLInputElement | null
  const display = row.querySelector('.slider-value') as HTMLElement | null
  if (input) input.value = String(value)
  if (display) display.textContent = String(value)
}

function toggle(label: string, value: boolean, onChange: (v: boolean) => void): HTMLElement {
  const id = 'toggle-' + Math.random().toString(36).slice(2)
  const input = el('input', { type: 'checkbox', id })
  if (value) input.setAttribute('checked', '')
  input.addEventListener('change', () => onChange((input as HTMLInputElement).checked))
  return el('label', { class: 'toggle', for: id }, input, el('span', { class: 'toggle-text' }, label))
}

function select<T extends string>(
  label: string,
  options: T[],
  value: T,
  onChange: (v: T) => void,
): HTMLElement {
  const sel = el('select')
  for (const opt of options) {
    const o = el('option', { value: opt }, opt)
    if (opt === value) o.setAttribute('selected', '')
    sel.append(o)
  }
  sel.addEventListener('change', () => onChange((sel as HTMLSelectElement).value as T))
  return el('div', { class: 'select-row' },
    el('label', {}, label),
    sel,
  )
}

function section(title: string, ...children: HTMLElement[]): HTMLDetailsElement {
  const details = el('details')
  details.setAttribute('open', '')
  details.append(el('summary', { class: 'section-title' }, title), ...children)
  return details
}

function btn(label: string, cls: string, onClick: () => void): HTMLButtonElement {
  const b = el('button', { class: cls }, label)
  b.addEventListener('click', onClick)
  return b
}

// ── Image source management ──────────────────────────────────────────────────

function revokeSource(): void {
  if (state.sourceImageURL) {
    URL.revokeObjectURL(state.sourceImageURL)
    state.sourceImageURL = null
  }
}

async function loadRandomImage(kind: 'cat' | 'dog' | 'dino'): Promise<void> {
  revokeSource()
  try {
    const url = await api.fetchRandomImage(kind)
    state.sourceImageURL = url
    state.imageSourceKind = kind
    schedulePreview()
  } catch (e) {
    alert('Failed to load image: ' + e)
  }
}

function handleFileUpload(file: File): void {
  revokeSource()
  state.sourceImageURL = URL.createObjectURL(file)
  state.imageSourceKind = 'upload'
  schedulePreview()
}

// ── Webcam dialog ─────────────────────────────────────────────────────────────

function buildWebcamDialog(onCapture: (dataURL: string) => void): { dialog: HTMLDialogElement; open: () => void } {
  const video = document.createElement('video')
  video.className = 'webcam-video'
  video.autoplay = true
  video.playsInline = true
  video.muted = true
  const countdownEl = el('div', { class: 'countdown hidden' })
  const captureBtn = btn('Capture', 'btn btn-brand', () => doCapture())
  const cancelBtn = btn('Cancel', 'btn btn-outline', () => {
    stopStream()
    dialog.close()
  })
  const cameraSelect = el('select', { class: 'hidden' })

  const dialog = el('dialog', { class: 'webcam-dialog' },
    el('div', { class: 'webcam-content' },
      el('h3', {}, 'Take a Photo'),
      video,
      countdownEl,
      cameraSelect,
      el('div', { class: 'webcam-actions' }, cancelBtn, captureBtn),
    ),
  )

  let stream: MediaStream | null = null

  function stopStream(): void {
    stream?.getTracks().forEach(t => t.stop())
    stream = null
  }

  async function startStream(deviceId?: string): Promise<void> {
    stopStream()
    const constraints: MediaStreamConstraints = {
      video: deviceId ? { deviceId: { exact: deviceId } } : { facingMode: { ideal: 'environment' } },
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia(constraints)
    } catch {
      stream = await navigator.mediaDevices.getUserMedia({ video: true })
    }
    ;(video as HTMLVideoElement).srcObject = stream

    const devices = await navigator.mediaDevices.enumerateDevices()
    const cameras = devices.filter(d => d.kind === 'videoinput')
    cameraSelect.innerHTML = ''
    cameras.forEach((c, i) => {
      const o = el('option', { value: c.deviceId }, c.label || `Camera ${i + 1}`)
      cameraSelect.append(o)
    })
    if (cameras.length > 1) cameraSelect.classList.remove('hidden')
    else cameraSelect.classList.add('hidden')
  }

  cameraSelect.addEventListener('change', () => startStream((cameraSelect as HTMLSelectElement).value))

  async function doCapture(): Promise<void> {
    captureBtn.disabled = true
    countdownEl.classList.remove('hidden')
    for (const n of [3, 2, 1]) {
      countdownEl.textContent = String(n)
      await new Promise(r => setTimeout(r, 1000))
    }
    countdownEl.classList.add('hidden')

    const v = video as HTMLVideoElement
    if (!v.videoWidth) {
      alert('No webcam frame available yet. Try again.')
      captureBtn.disabled = false
      return
    }
    const canvas = document.createElement('canvas')
    canvas.width = v.videoWidth
    canvas.height = v.videoHeight
    canvas.getContext('2d')!.drawImage(v, 0, 0)
    const dataURL = canvas.toDataURL('image/png')
    stopStream()
    dialog.close()
    onCapture(dataURL)
    captureBtn.disabled = false
  }

  function open(): void {
    if (location.protocol !== 'https:' && location.hostname !== 'localhost' && location.hostname !== '127.0.0.1') {
      alert('Camera access requires HTTPS.')
      return
    }
    dialog.showModal()
    startStream().catch(e => {
      dialog.close()
      alert('Could not access webcam: ' + e.message)
    })
  }

  document.body.append(dialog)
  return { dialog, open }
}

// ── ZPL preview dialog removed — preview is now inline ──────────────────────

// ── Build Image Controls panel ───────────────────────────────────────────────

function buildImageControls(webcam: { open: () => void }): HTMLElement {
  return section('Image Options',
    el('div', { class: 'btn-grid' },
      btn('Get Cat', 'btn btn-small', () => loadRandomImage('cat')),
      btn('Get Dog', 'btn btn-small', () => loadRandomImage('dog')),
      btn('Get Dino', 'btn btn-small', () => loadRandomImage('dino')),
      btn('Webcam', 'btn btn-small', () => webcam.open()),
      btn('Clear', 'btn btn-small btn-danger', () => {
        revokeSource()
        state.imageSourceKind = 'none'
        schedulePreview()
      }),
    ),
    el('div', { class: 'toggle-row' },
      toggle('Crop', state.cropImage, v => { state.cropImage = v; schedulePreview() }),
      toggle('Comic', state.comicFilter, v => { state.comicFilter = v; schedulePreview() }),
      toggle('Dither', state.ditherPreview, v => { state.ditherPreview = v; schedulePreview() }),
    ),
    slider('Black', 0, 255, 1, state.blackPoint, v => { state.blackPoint = v; schedulePreview() }),
    slider('White', 0, 255, 1, state.whitePoint, v => { state.whitePoint = v; schedulePreview() }),
    slider('Contrast', 0.3, 3.0, 0.1, state.contrast, v => { state.contrast = v; schedulePreview() }),
    ...(() => {
      const xOff = slider('X-Offset', -200, 200, 1, state.imgOffsetX, v => { state.imgOffsetX = v; schedulePreview() })
      const yOff = slider('Y-Offset', -200, 200, 1, state.imgOffsetY, v => { state.imgOffsetY = v; schedulePreview() })
      const rot = select('Rotate Image', ['0', '90', '180', '270'] as const, String(state.rotateImageAngle) as '0', v => {
        state.rotateImageAngle = parseInt(v)
        state.imgOffsetX = 0; state.imgOffsetY = 0
        resetSlider(xOff, 0); resetSlider(yOff, 0)
        schedulePreview()
      })
      return [rot, xOff, yOff] as HTMLElement[]
    })(),
  )
}

// ── Build Text Controls panel ────────────────────────────────────────────────

function buildFontPicker(onChange: (name: string) => void): HTMLElement {
  const fonts = [{ name: '(default)', path: '' }, ...state.fonts]
  let current = state.fontName || '(default)'

  const labelEl = el('span', { class: 'font-picker-label' })
  const listEl  = el('div',  { class: 'font-picker-list hidden' })
  const root    = el('div',  { class: 'font-picker' }, labelEl, listEl)

  function updateLabel(): void {
    labelEl.textContent = current
    const f = fonts.find(f => f.name === current)
    ;(labelEl as HTMLElement).style.fontFamily = (f && f.path) ? `"${current}", sans-serif` : ''
  }

  function close(): void { listEl.classList.add('hidden') }
  function open(): void  { listEl.classList.remove('hidden'); listEl.scrollTop = 0 }

  fonts.forEach(f => {
    const item = el('div', { class: 'font-picker-item' }, f.name)
    ;(item as HTMLElement).style.fontFamily = f.path ? `"${f.name}", sans-serif` : ''
    if (f.name === current) item.classList.add('selected')
    item.addEventListener('mousedown', e => {
      e.preventDefault()
      current = f.name
      listEl.querySelectorAll('.font-picker-item').forEach(i => i.classList.remove('selected'))
      item.classList.add('selected')
      updateLabel()
      close()
      onChange(f.name === '(default)' ? '' : f.name)
    })
    listEl.append(item)
  })

  labelEl.addEventListener('click', () => listEl.classList.contains('hidden') ? open() : close())
  document.addEventListener('click', e => { if (!root.contains(e.target as Node)) close() })

  updateLabel()
  return root
}

function buildTextControls(): HTMLElement {
  const fontPicker = buildFontPicker(name => {
    state.fontName = name
    schedulePreview()
  })

  const textArea = el('textarea', { class: 'text-input', placeholder: 'Label text…' })
  ;(textArea as HTMLTextAreaElement).rows = 3
  ;(textArea as HTMLTextAreaElement).value = state.text
  textArea.addEventListener('input', () => { state.text = (textArea as HTMLTextAreaElement).value; schedulePreview() })

  return section('Text Overlay',
    textArea,
    el('div', { class: 'select-row' }, el('label', {}, 'Font'), fontPicker),
    slider('Size', 8, 200, 1, state.textSize, v => { state.textSize = v; schedulePreview() }),
    ...(() => {
      const xOff = slider('X-Offset', -500, 500, 1, state.textOffsetX, v => { state.textOffsetX = v; schedulePreview() })
      const yOff = slider('Y-Offset', -500, 500, 1, state.textOffsetY, v => { state.textOffsetY = v; schedulePreview() })
      const rot = slider('Rotate', -180, 180, 1, state.rotateText, v => { state.rotateText = v; schedulePreview() })
      const hAlign = select('H-Align', ['Left', 'Center', 'Right'] as const, state.hAlign, v => {
        state.hAlign = v; state.textOffsetX = 0; state.rotateText = 0
        resetSlider(xOff, 0); resetSlider(rot, 0); schedulePreview()
      })
      const vAlign = select('V-Align', ['Top', 'Center', 'Bottom'] as const, state.vAlign, v => {
        state.vAlign = v; state.textOffsetY = 0; state.rotateText = 0
        resetSlider(yOff, 0); resetSlider(rot, 0); schedulePreview()
      })
      return [hAlign, vAlign, xOff, yOff, rot] as HTMLElement[]
    })(),
    el('div', { class: 'toggle-row' },
      toggle('Black Text', state.blackText, v => { state.blackText = v; schedulePreview() }),
      toggle('Outline', state.outline, v => { state.outline = v; schedulePreview() }),
    ),
  )
}

// ── Build Barcode Controls panel ─────────────────────────────────────────────

function buildBarcodeControls(): HTMLElement {
  const dataInput = el('input', { type: 'text', class: 'text-input', placeholder: 'Barcode data…' })
  ;(dataInput as HTMLInputElement).value = state.barcodeData
  dataInput.addEventListener('input', () => { state.barcodeData = (dataInput as HTMLInputElement).value })

  const generateBtn = btn('Generate Barcode', 'btn btn-primary', () => {
    const data = state.barcodeData.trim()
    if (!data) { alert('Enter barcode data first.'); return }
    try {
      const bc = generateBarcodeCanvas(data, state.barcodeType, state.barcodeShowValue)

      if (state.barcodeAttachEnd) {
        // Bake below source image
        const size = Math.max(1, state.barcodeSize)
        const scaled = document.createElement('canvas')
        scaled.width = bc.width * size
        scaled.height = bc.height * size
        const sc = scaled.getContext('2d')!
        sc.imageSmoothingEnabled = false
        sc.drawImage(bc, 0, 0, scaled.width, scaled.height)
        // Store as new source
        revokeSource()
        if (state.sourceImageURL) {
          const img = new Image()
          img.onload = () => {
            const combined = document.createElement('canvas')
            combined.width = Math.max(img.width, scaled.width)
            combined.height = img.height + scaled.height
            const cc = combined.getContext('2d')!
            cc.fillStyle = '#fff'
            cc.fillRect(0, 0, combined.width, combined.height)
            cc.drawImage(img, (combined.width - img.width) / 2, 0)
            cc.drawImage(scaled, (combined.width - scaled.width) / 2, img.height)
            combined.toBlob(blob => {
              if (blob) { state.sourceImageURL = URL.createObjectURL(blob); schedulePreview() }
            })
          }
          img.src = state.sourceImageURL
        } else {
          scaled.toBlob(blob => {
            if (blob) { state.sourceImageURL = URL.createObjectURL(blob); schedulePreview() }
          })
        }
        state.barcodeCanvas = null
      } else {
        state.barcodeCanvas = bc
      }
      schedulePreview()
    } catch (e) {
      alert('Barcode error: ' + e)
    }
  })

  const clearBtn = btn('Clear Barcode', 'btn btn-outline', () => { state.barcodeCanvas = null; schedulePreview() })

  return section('Barcode',
    dataInput,
    select('Type', ['QR', 'Code128', 'Aztec', 'DataMatrix'] as const, state.barcodeType, v => { state.barcodeType = v }),
    slider('Size', 1, 10, 1, state.barcodeSize, v => { state.barcodeSize = v }),
    el('div', { class: 'toggle-row' },
      toggle('Show Value', state.barcodeShowValue, v => { state.barcodeShowValue = v }),
      toggle('Attach End', state.barcodeAttachEnd, v => { state.barcodeAttachEnd = v }),
    ),
    ...(() => {
      const xOff = slider('X-Offset', -500, 500, 1, state.barcodeOffsetX, v => { state.barcodeOffsetX = v; schedulePreview() })
      const yOff = slider('Y-Offset', -500, 500, 1, state.barcodeOffsetY, v => { state.barcodeOffsetY = v; schedulePreview() })
      const hAlign = select('H-Align', ['Left', 'Center', 'Right'] as const, state.barcodeHAlign, v => {
        state.barcodeHAlign = v; state.barcodeOffsetX = 0
        resetSlider(xOff, 0); schedulePreview()
      })
      const vAlign = select('V-Align', ['Top', 'Center', 'Bottom'] as const, state.barcodeVAlign, v => {
        state.barcodeVAlign = v; state.barcodeOffsetY = 0
        resetSlider(yOff, 0); schedulePreview()
      })
      return [hAlign, vAlign, xOff, yOff] as HTMLElement[]
    })(),
    slider('Rotate', 0, 359, 1, state.barcodeRotate, v => { state.barcodeRotate = v; schedulePreview() }),
    el('div', { class: 'btn-row' }, generateBtn, clearBtn),
  )
}

// ── Build Raw ZPL tab ────────────────────────────────────────────────────────

function buildZPLTab(): HTMLElement {
  const zplPrinters = state.printers.filter(p => p.type === 'zpl')
  let selectedZPLIndex = zplPrinters.length > 0 ? zplPrinters[0].index : -1

  // Printer selector (ZPL-only)
  const printerSel = el('select', { class: 'printer-select' })
  if (!zplPrinters.length) {
    printerSel.append(el('option', {}, '(no ZPL printers configured)'))
  } else {
    zplPrinters.forEach(p => {
      const shape = p.label.length > 0
        ? `${p.label.width}×${p.label.length}mm`
        : `${p.label.width}mm endless`
      const serial = p.serial ? ` · ${p.serial}` : ''
      printerSel.append(el('option', { value: String(p.index) }, `${p.name}${serial} · ${p.label.isRound ? 'ø' : ''}${shape}`))
    })
  }
  printerSel.addEventListener('change', () => {
    selectedZPLIndex = parseInt((printerSel as HTMLSelectElement).value)
    scheduleZPLPreview()
  })

  const statusEl = el('div', { class: 'status-msg hidden' })
  let zplStatusTimer: number | null = null

  function showStatus(msg: string, ok: boolean, autoDismissMs = 3500): void {
    if (zplStatusTimer !== null) clearTimeout(zplStatusTimer)
    statusEl.textContent = msg
    statusEl.className = 'status-msg ' + (ok ? 'status-ok' : 'status-err')
    statusEl.classList.remove('hidden')
    if (autoDismissMs > 0) {
      zplStatusTimer = window.setTimeout(() => statusEl.classList.add('hidden'), autoDismissMs)
    }
  }

  // Inline preview
  const previewImg = el('img', { class: 'zpl-inline-preview', alt: 'ZPL preview' })
  const previewWrap = el('div', { class: 'zpl-preview-wrap' },
    el('div', { class: 'zpl-preview-placeholder' }, 'Preview will appear here'),
    previewImg,
  )

  let zplPreviewTimer: number | null = null
  function scheduleZPLPreview(): void {
    if (zplPreviewTimer !== null) clearTimeout(zplPreviewTimer)
    zplPreviewTimer = window.setTimeout(async () => {
      if (selectedZPLIndex < 0) return
      try {
        const url = await api.previewZPL(selectedZPLIndex, state.rawZPL)
        ;(previewImg as HTMLImageElement).src = url
        previewImg.classList.remove('hidden')
        previewWrap.querySelector('.zpl-preview-placeholder')?.classList.add('hidden')
      } catch {
        // silently ignore preview errors while typing
      }
    }, 600)
  }

  const textarea = el('textarea', { class: 'zpl-textarea' })
  ;(textarea as HTMLTextAreaElement).spellcheck = false
  ;(textarea as HTMLTextAreaElement).value = state.rawZPL
  textarea.addEventListener('input', () => {
    state.rawZPL = (textarea as HTMLTextAreaElement).value
    scheduleZPLPreview()
  })

  const sendBtn = btn('Send to Printer', 'btn btn-primary', async () => {
    if (selectedZPLIndex < 0) { showStatus('No ZPL printer available.', false); return }
    sendBtn.disabled = true
    try {
      await api.sendRawZPL(selectedZPLIndex, state.rawZPL)
      showStatus('ZPL sent!', true)
    } catch (e) {
      showStatus('Send ZPL failed: ' + (e instanceof Error ? e.message : String(e)), false, 0)
    } finally {
      sendBtn.disabled = false
    }
  })

  // Trigger initial preview if we have a printer
  if (selectedZPLIndex >= 0) scheduleZPLPreview()

  return el('div', { class: 'tab-content' },
    el('h3', {}, 'Raw ZPL Editor'),
    el('div', { class: 'zpl-toolbar' },
      printerSel,
      sendBtn,
    ),
    statusEl,
    el('div', { class: 'zpl-editor-grid' },
      textarea,
      previewWrap,
    ),
  )
}

// ── Build Cable Label tab ────────────────────────────────────────────────────

function buildCableLabelTab(): HTMLElement {
  const zplPrinters = state.printers.filter(p => p.type === 'zpl')
  let selectedZPLIndex = zplPrinters.length > 0 ? zplPrinters[0].index : -1

  // Printer selector (ZPL-only)
  const printerSel = el('select', { class: 'printer-select' })
  if (!zplPrinters.length) {
    printerSel.append(el('option', {}, '(no ZPL printers configured)'))
  } else {
    zplPrinters.forEach(p => {
      const shape = p.label.length > 0
        ? `${p.label.width}×${p.label.length}mm`
        : `${p.label.width}mm endless`
      const serial = p.serial ? ` · ${p.serial}` : ''
      printerSel.append(el('option', { value: String(p.index) }, `${p.name}${serial} · ${p.label.isRound ? 'ø' : ''}${shape}`))
    })
  }
  printerSel.addEventListener('change', () => {
    selectedZPLIndex = parseInt((printerSel as HTMLSelectElement).value)
    schedulePreview()
  })

  const statusEl = el('div', { class: 'status-msg hidden' })
  let zplStatusTimer: number | null = null

  function showStatus(msg: string, ok: boolean, autoDismissMs = 3500): void {
    if (zplStatusTimer !== null) clearTimeout(zplStatusTimer)
    statusEl.textContent = msg
    statusEl.className = 'status-msg ' + (ok ? 'status-ok' : 'status-err')
    statusEl.classList.remove('hidden')
    if (autoDismissMs > 0) {
      zplStatusTimer = window.setTimeout(() => statusEl.classList.add('hidden'), autoDismissMs)
    }
  }

  // Text input
  const textInput = el('input', { type: 'text', class: 'text-input', placeholder: 'Enter cable label text…' })

  // Inline preview
  const previewImg = el('img', { class: 'zpl-inline-preview', alt: 'Cable label preview' })
  const previewWrap = el('div', { class: 'zpl-preview-wrap' },
    el('div', { class: 'zpl-preview-placeholder' }, 'Preview will appear here'),
    previewImg,
  )

  let zplPreviewTimer: number | null = null
  
  function generateZPL(): string {
    const input = (textInput as HTMLInputElement).value || ''
    return `^XA\n^FO40,400^A0B,50,40^FD${input}^FS\n^FO120,400^A0R,50,40^FD${input}^FS\n^XZ`
  }

  function schedulePreview(): void {
    if (zplPreviewTimer !== null) clearTimeout(zplPreviewTimer)
    zplPreviewTimer = window.setTimeout(async () => {
      if (selectedZPLIndex < 0) return
      try {
        const zpl = generateZPL()
        const url = await api.previewZPL(selectedZPLIndex, zpl)
        ;(previewImg as HTMLImageElement).src = url
        previewImg.classList.remove('hidden')
        previewWrap.querySelector('.zpl-preview-placeholder')?.classList.add('hidden')
      } catch {
        // silently ignore preview errors while typing
      }
    }, 600)
  }

  textInput.addEventListener('input', () => {
    schedulePreview()
  })

  const sendBtn = btn('Send to Printer', 'btn btn-primary', async () => {
    if (selectedZPLIndex < 0) { showStatus('No ZPL printer available.', false); return }
    if (!(textInput as HTMLInputElement).value.trim()) { showStatus('Enter cable label text first.', false); return }
    sendBtn.disabled = true
    try {
      const zpl = generateZPL()
      await api.sendRawZPL(selectedZPLIndex, zpl)
      showStatus('Cable label sent!', true)
    } catch (e) {
      showStatus('Send failed: ' + (e instanceof Error ? e.message : String(e)), false, 0)
    } finally {
      sendBtn.disabled = false
    }
  })

  // Trigger initial preview if we have a printer
  if (selectedZPLIndex >= 0) schedulePreview()

  return el('div', { class: 'tab-content' },
    el('h3', {}, 'Cable Label'),
    el('div', { class: 'zpl-toolbar' },
      printerSel,
      sendBtn,
    ),
    statusEl,
    textInput,
    el('div', { class: 'zpl-editor-grid' },
      previewWrap,
    ),
  )
}

// ── Build About tab ───────────────────────────────────────────────────────────

function buildAboutTab(): HTMLElement {
  const statsEl = el('div', { class: 'about-stats' })
  const readmeEl = el('div', { class: 'about-readme' })
  const root = el('div', { class: 'tab-content' }, statsEl, readmeEl)

  // Load stats
  api.fetchStats().then(s => {
    const rows: Array<[string, number]> = [
      ['Cats',            s.printed_cats],
      ['Dogs',            s.printed_dogs],
      ['Dinos',           s.printed_dinos],
      ['Webcam',          s.printed_webcam_images],
      ['Uploaded images', s.printed_uploaded_images],
      ['No image',        s.printed_without_image],
      ['Total',           s.printed_total],
    ]
    const tbody = el('tbody')
    for (const [label, count] of rows) {
      const isTotals = label === 'Total'
      const tr = el('tr', { class: isTotals ? 'stats-total-row' : '' },
        el('td', {}, label),
        el('td', { class: 'stats-count' }, String(count)),
      )
      tbody.append(tr)
    }
    statsEl.append(
      el('h3', {}, 'Print Statistics'),
      el('table', { class: 'stats-table' },
        el('thead', {},
          el('tr', {},
            el('th', {}, 'Source'),
            el('th', {}, 'Count'),
          ),
        ),
        tbody,
      ),
    )
  }).catch(() => {
    statsEl.append(el('p', { class: 'status-err' }, 'Could not load statistics.'))
  })

  // Load README
  api.fetchReadme().then(md => {
    const html = marked.parse(md) as string
    readmeEl.innerHTML = html
  }).catch(() => {
    readmeEl.append(el('p', { class: 'status-err' }, 'Could not load README.'))
  })

  return root
}
// ── Build Config tab ────────────────────────────────────────────────────────────

function buildConfigTab(): HTMLElement {
  const pwdInput = el('input', { type: 'password', class: 'text-input config-pwd-input', placeholder: 'Config password' })
  const editorWrap = el('div', { class: 'config-editor-wrap hidden' })
  const statusEl = el('div', { class: 'status-msg hidden' })

  // ── CodeMirror JSON editor ──
  const cmView = new EditorView({
    state: EditorState.create({ doc: '', extensions: [basicSetup, json(), EditorView.lineWrapping] }),
    parent: editorWrap,
  })

  function getEditorValue(): string {
    return cmView.state.doc.toString()
  }

  function setEditorValue(text: string): void {
    cmView.dispatch({
      changes: { from: 0, to: cmView.state.doc.length, insert: text },
    })
  }

  function showStatus(msg: string, ok: boolean): void {
    statusEl.textContent = msg
    statusEl.className = 'status-msg ' + (ok ? 'status-ok' : 'status-err')
    setTimeout(() => statusEl.classList.add('hidden'), 4500)
  }

  const saveBtn = btn('Save Config', 'btn btn-primary hidden', async () => {
    saveBtn.disabled = true
    try {
      await api.saveConfig((pwdInput as HTMLInputElement).value, getEditorValue())
      showStatus('Saved — changes are live immediately.', true)
    } catch (e) {
      showStatus('Save failed: ' + (e instanceof Error ? e.message : String(e)), false)
    } finally {
      saveBtn.disabled = false
    }
  })

  const loadBtn = btn('Load', 'btn btn-secondary', async () => {
    loadBtn.disabled = true
    try {
      const json = await api.fetchConfig((pwdInput as HTMLInputElement).value)
      setEditorValue(json)
      editorWrap.classList.remove('hidden')
      saveBtn.classList.remove('hidden')
      showStatus('Config loaded.', true)
    } catch (e) {
      showStatus('Failed: ' + (e instanceof Error ? e.message : String(e)), false)
    } finally {
      loadBtn.disabled = false
    }
  })

  pwdInput.addEventListener('keydown', (e: Event) => {
    if ((e as KeyboardEvent).key === 'Enter') loadBtn.click()
  })

  // ── Scan section ──────────────────────────────────────────────────────────

  const scanResultsEl = el('div', { class: 'scan-results hidden' })

  function addPrinterToConfig(p: import('./types').ScannedPrinter): void {
    const newEntry = {
      name: p.name,
      serial: p.serial,
      connection: p.connection,
      type: p.type,
      backend: p.backend,
      dpi: p.dpi,
      label: { cut: p.type === 'brother_ql', format: p.labelFormat, vertical_offset: 0 },
    }

    const current = getEditorValue()
    if (!current.trim()) {
      showStatus('Load the config first, then add printers.', false)
      return
    }
    try {
      const cfg = JSON.parse(current)
      if (!Array.isArray(cfg.printers)) cfg.printers = []
      cfg.printers.push(newEntry)
      setEditorValue(JSON.stringify(cfg, null, 4))
      editorWrap.classList.remove('hidden')
      saveBtn.classList.remove('hidden')
      showStatus(`"${p.name}" added — review and Save Config.`, true)
    } catch {
      showStatus('Could not parse config JSON.', false)
    }
  }

  const scanBtn = btn('Scan for Printers', 'btn btn-secondary', async () => {
    scanBtn.disabled = true
    scanResultsEl.innerHTML = ''
    scanResultsEl.classList.add('hidden')
    try {
      const found = await api.scanPrinters((pwdInput as HTMLInputElement).value)
      if (!found.length) {
        scanResultsEl.append(el('p', { class: 'scan-empty' }, 'No supported printers found on USB.'))
      } else {
        scanResultsEl.append(el('h4', { class: 'scan-heading' }, `Found ${found.length} printer${found.length > 1 ? 's' : ''}`))
        for (const p of found) {
          const addBtn = btn('Add to Config', 'btn btn-primary btn-sm', () => addPrinterToConfig(p))
          scanResultsEl.append(
            el('div', { class: 'scan-result-item' },
              el('div', { class: 'scan-result-info' },
                el('strong', {}, p.name),
                el('span', { class: 'scan-result-meta' },
                  `${p.type} · ${p.dpi} DPI · ${p.labelFormat}${p.serial ? ` · S/N ${p.serial}` : ''}`,
                ),
                el('code', { class: 'scan-result-conn' }, p.connection),
              ),
              addBtn,
            ),
          )
        }
      }
      scanResultsEl.classList.remove('hidden')
    } catch (e) {
      showStatus('Scan failed: ' + (e instanceof Error ? e.message : String(e)), false)
    } finally {
      scanBtn.disabled = false
    }
  })

  return el('div', { class: 'tab-content' },
    el('h3', {}, 'Config Editor'),
    el('p', { class: 'config-hint' }, 'Enter the config password to load and edit config.json.'),
    el('div', { class: 'config-pwd-row' },
      pwdInput,
      loadBtn,
      scanBtn,
    ),
    statusEl,
    scanResultsEl,
    editorWrap,
    el('div', { class: 'btn-row' }, saveBtn),
  )
}
// ── Main app builder ─────────────────────────────────────────────────────────

export async function initApp(appEl: HTMLElement, initialState: AppState, appName = 'Gostikka', appSubtitle = '', zplRawEnabled = true): Promise<void> {
  state = initialState
  await loadAllFonts(state.fonts)

  // ── Webcam ──
  const webcam = buildWebcamDialog(dataURL => {
    revokeSource()
    state.sourceImageURL = dataURL
    state.imageSourceKind = 'webcam'
    schedulePreview()
  })

  // ── Preview canvas ──
  previewCanvas = el('canvas', { class: 'preview-canvas' })

  // ── File upload zone ──
  const uploadInput = el('input', { type: 'file', accept: 'image/*,.pdf', class: 'hidden', id: 'upload-input' })
  uploadInput.addEventListener('change', () => {
    const f = (uploadInput as HTMLInputElement).files?.[0]
    if (f) handleFileUpload(f)
  })
  const uploadZone = el('label', { for: 'upload-input', class: 'upload-zone' },
    uploadInput,
    el('span', {}, 'Click or drop image / PDF'),
  )
  uploadZone.addEventListener('dragover', e => { e.preventDefault(); uploadZone.classList.add('drag-over') })
  uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('drag-over'))
  uploadZone.addEventListener('drop', e => {
    e.preventDefault()
    uploadZone.classList.remove('drag-over')
    const f = (e as DragEvent).dataTransfer?.files[0]
    if (f) handleFileUpload(f)
  })

  // ── Printer selector ──
  const printerSel = el('select', { class: 'printer-select' })
  if (!state.printers.length) {
    printerSel.append(el('option', {}, '(no printers configured)'))
  } else {
    state.printers.forEach((p, i) => {
      const shape = p.label.length > 0
        ? `${p.label.width}×${p.label.length}mm`
        : `${p.label.width}mm endless`
      const serial = p.serial ? ` · ${p.serial}` : ''
      const o = el('option', { value: String(i) }, `${p.name}${serial} · ${p.label.isRound ? 'ø' : ''}${shape}`)
      if (i === state.selectedPrinterIndex) o.setAttribute('selected', '')
      printerSel.append(o)
    })
  }
  printerSel.addEventListener('change', () => {
    state.selectedPrinterIndex = parseInt((printerSel as HTMLSelectElement).value)
    schedulePreview()
  })

  // ── Print / Download buttons ──
  const statusEl = el('div', { class: 'status-msg hidden' })
  let statusTimer: number | null = null

  function showStatus(msg: string, ok: boolean, autoDismissMs = 3500): void {
    if (statusTimer !== null) clearTimeout(statusTimer)
    statusEl.textContent = msg
    statusEl.className = 'status-msg ' + (ok ? 'status-ok' : 'status-err')
    statusEl.classList.remove('hidden')
    if (autoDismissMs > 0) {
      statusTimer = window.setTimeout(() => statusEl.classList.add('hidden'), autoDismissMs)
    }
  }

  const printBtn = btn('Print Stikka', 'btn btn-primary btn-large', async () => {
    const printer = state.printers[state.selectedPrinterIndex]
    if (!printer) { alert('Select a printer.'); return }
    printBtn.disabled = true
    statusEl.classList.add('hidden')
    try {
      const rendered = await renderLabel(state, printer)
      await api.printImage(printer.index, rendered.toDataURL('image/png'))
      showStatus('Print job sent!', true)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      showStatus('Print error: ' + msg, false, 0)  // 0 = stay visible until next action
    } finally {
      printBtn.disabled = false
    }
  })

  const downloadBtn = btn('Download', 'btn btn-secondary btn-large', async () => {
    const printer = state.printers[state.selectedPrinterIndex]
    if (!printer) { alert('Select a printer.'); return }
    downloadBtn.disabled = true
    try {
      const rendered = await renderLabel(state, printer)
      const a = el('a', { download: 'stikka.png', href: rendered.toDataURL('image/png') })
      a.click()
    } finally {
      downloadBtn.disabled = false
    }
  })

  // ── Tab system ──
  const allTabs: Array<{ name: string; panel: HTMLElement }> = [
    { name: 'Label',   panel: el('div', { class: 'tab-panel active', id: 'tab-label' }) },
    ...(zplRawEnabled ? [{ name: 'Raw ZPL', panel: el('div', { class: 'tab-panel', id: 'tab-zpl' }) }] : []),
    ...(zplRawEnabled ? [{ name: 'Cable Label', panel: el('div', { class: 'tab-panel', id: 'tab-cable' }) }] : []),
    { name: 'About',   panel: el('div', { class: 'tab-panel', id: 'tab-about' }) },
    { name: 'Config',  panel: el('div', { class: 'tab-panel', id: 'tab-config' }) },
  ]
  const tabBtns: HTMLButtonElement[] = []
  const tabPanels = allTabs.map(t => t.panel)

  allTabs.forEach(({ name }, i) => {
    const isConfig = name === 'Config'
    const b = el('button', { class: 'tab-btn' + (i === 0 ? ' active' : '') + (isConfig ? ' tab-btn-right' : '') }, name)
    b.addEventListener('click', () => {
      tabBtns.forEach(tb => tb.classList.remove('active'))
      tabPanels.forEach(tp => tp.classList.remove('active'))
      b.classList.add('active')
      tabPanels[i].classList.add('active')
    })
    tabBtns.push(b)
  })

  // ── Label tab layout ──
  const labelTab = tabPanels[0]
  labelTab.append(
    // Printer row
    el('div', { class: 'printer-row' },
      printerSel,
      downloadBtn,
      printBtn,
    ),
    statusEl,
    el('hr', {}),
    // Main grid: preview | controls
    el('div', { class: 'main-grid' },
      // Left: preview + upload
      el('div', { class: 'preview-col' },
        el('div', { class: 'preview-wrap' }, previewCanvas),
        uploadZone,
      ),
      // Right: control panels
      el('div', { class: 'controls-col' },
        buildImageControls(webcam),
        buildTextControls(),
        buildBarcodeControls(),
      ),
    ),
  )

  // ── Other tabs ──
  const getPanel = (id: string) => tabPanels.find(p => p.id === id)!
  if (zplRawEnabled) getPanel('tab-zpl').append(buildZPLTab())
  if (zplRawEnabled) getPanel('tab-cable').append(buildCableLabelTab())
  getPanel('tab-about').append(buildAboutTab())
  getPanel('tab-config').append(buildConfigTab())

  // ── Root structure ──
  appEl.innerHTML = ''
  appEl.append(
    el('header', { class: 'app-header' },
      el('div', { class: 'header-title' }, appName),
      ...(appSubtitle ? [el('div', { class: 'header-subtitle' }, appSubtitle)] : []),
    ),
    el('main', { class: 'app-main' },
      el('div', { class: 'tab-bar' }, ...tabBtns),
      ...tabPanels,
    ),
  )

  // Initial preview
  schedulePreview()
}

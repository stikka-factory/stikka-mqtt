/**
 * ui.ts — Builds and wires the entire Gostikka UI.
 *
 * No external framework — plain DOM manipulation with TypeScript.
 */

import type { AppState, FontInfo, PrinterInfo, StaticModeConfig } from './types'
import { renderLabel, generateBarcodeCanvas, loadAllFonts, loadFont } from './editor'
import { renderPDFPageAsDataURL } from './pdf'
import { saveCustomFont } from './static-config'
import * as api from './mqtt-api'
import { marked } from 'marked'

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

async function handleFileUpload(file: File): Promise<void> {
  revokeSource()
  try {
    if (file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')) {
      state.sourceImageURL = await renderPDFPageAsDataURL(file)
    } else {
      state.sourceImageURL = URL.createObjectURL(file)
    }
    state.imageSourceKind = 'upload'
    schedulePreview()
  } catch (e) {
    alert('Could not load upload: ' + (e instanceof Error ? e.message : String(e)))
  }
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

function buildSettingsTab(
  onApplied: () => void,
  settingsPassword?: string,
): HTMLElement {
  const root = el('div', { class: 'tab-content' })
  const cfg = api.getStaticRuntimeConfig()

  if (!cfg) {
    root.append(el('p', { class: 'status-err' }, 'Runtime config is unavailable.'))
    return root
  }

  const unlockWrap = el('div')
  const editorWrap = el('div', { class: 'hidden' })
  const statusEl = el('div', { class: 'status-msg hidden' })

  const showStatus = (msg: string, ok: boolean): void => {
    statusEl.textContent = msg
    statusEl.className = 'status-msg ' + (ok ? 'status-ok' : 'status-err')
    statusEl.classList.remove('hidden')
  }

  const appNameInput = el('input', { type: 'text', class: 'text-input', placeholder: 'App name', value: cfg.app.name }) as HTMLInputElement
  const appSubtitleInput = el('input', { type: 'text', class: 'text-input', placeholder: 'Subtitle', value: cfg.app.subtitle }) as HTMLInputElement
  const zplExampleInput = el('textarea', { class: 'text-input', placeholder: 'ZPL example' }) as HTMLTextAreaElement
  zplExampleInput.value = cfg.app.zplExample
  const zplRawEnabledInput = el('input', { type: 'checkbox' }) as HTMLInputElement
  zplRawEnabledInput.checked = cfg.app.zplRawEnabled
  const cableEnabledInput = el('input', { type: 'checkbox' }) as HTMLInputElement
  cableEnabledInput.checked = cfg.app.cableLabelEnabled
  const cableTemplateInput = el('textarea', { class: 'text-input', placeholder: 'Cable label ZPL template' }) as HTMLTextAreaElement
  cableTemplateInput.value = cfg.app.cableLabelZPLTemplate ?? ''

  const mqttBrokerInput = el('input', { type: 'text', class: 'text-input', placeholder: 'ws://broker:9001', value: cfg.mqtt?.brokerURL ?? '' }) as HTMLInputElement
  const mqttUserInput = el('input', { type: 'text', class: 'text-input', placeholder: 'MQTT username (optional)', value: cfg.mqtt?.username ?? '' }) as HTMLInputElement
  const mqttPasswordInput = el('input', { type: 'password', class: 'text-input', placeholder: 'MQTT password (optional)', value: cfg.mqtt?.password ?? '' }) as HTMLInputElement
  const mqttClientPrefixInput = el('input', { type: 'text', class: 'text-input', placeholder: 'stikka-web', value: cfg.mqtt?.clientIdPrefix ?? 'stikka-web' }) as HTMLInputElement
  const mqttDiscoveryWaitInput = el('input', { type: 'number', class: 'text-input', placeholder: '1500', value: String(cfg.mqtt?.discoveryWaitMs ?? 1500) }) as HTMLInputElement
  const settingsPwdInput = el('input', { type: 'text', class: 'text-input', placeholder: 'settings page password', value: cfg.mqttSettingsPassword ?? '' }) as HTMLInputElement

  const applyBtn = btn('Apply Settings', 'btn btn-primary', async () => {
    const next: StaticModeConfig = {
      mode: 'mqtt',
      app: {
        name: appNameInput.value.trim() || 'Stikka-NG',
        subtitle: appSubtitleInput.value.trim(),
        zplExample: zplExampleInput.value,
        zplRawEnabled: zplRawEnabledInput.checked,
        cableLabelEnabled: cableEnabledInput.checked,
        cableLabelZPLTemplate: cableTemplateInput.value,
      },
      mqttSettingsPassword: settingsPwdInput.value.trim() || undefined,
      mqtt: {
        brokerURL: mqttBrokerInput.value.trim(),
        username: mqttUserInput.value.trim() || undefined,
        password: mqttPasswordInput.value || undefined,
        clientIdPrefix: mqttClientPrefixInput.value.trim() || 'stikka-web',
        discoveryWaitMs: Math.max(0, parseInt(mqttDiscoveryWaitInput.value || '1500')),
      },
    }

    if (!next.mqtt.brokerURL) {
      showStatus('Broker URL is required.', false)
      return
    }

    applyBtn.disabled = true
    try {
      await api.updateStaticRuntimeConfig(next)
      showStatus('Settings applied. Reloading UI state.', true)
      onApplied()
    } catch (e) {
      showStatus('Apply failed: ' + (e instanceof Error ? e.message : String(e)), false)
    } finally {
      applyBtn.disabled = false
    }
  })

  const unlockInput = el('input', { type: 'password', class: 'text-input config-pwd-input', placeholder: 'Settings password' }) as HTMLInputElement
  const unlockBtn = btn('Unlock', 'btn btn-secondary', () => {
    const required = settingsPassword ?? ''
    if (!required || unlockInput.value === required) {
      unlockWrap.classList.add('hidden')
      editorWrap.classList.remove('hidden')
      unlockInput.value = ''
      showStatus('Settings unlocked.', true)
      return
    }
    showStatus('Wrong settings password.', false)
  })

  unlockInput.addEventListener('keydown', (e: Event) => {
    if ((e as KeyboardEvent).key === 'Enter') unlockBtn.click()
  })

  unlockWrap.append(
    el('p', { class: 'config-hint' }, 'Enter settings password to edit runtime config.'),
    el('div', { class: 'config-pwd-row' }, unlockInput, unlockBtn),
  )

  // ── Font upload — deliberately not gated by the settings password; any
  // visitor can add a font for use in the Text Overlay picker. ──
  const fontFileInput = el('input', { type: 'file', accept: '.ttf,.otf,.woff,.woff2', class: 'hidden', id: 'font-upload-input' })
  fontFileInput.addEventListener('change', () => {
    const f = (fontFileInput as HTMLInputElement).files?.[0]
    if (f) void handleFontUpload(f)
    ;(fontFileInput as HTMLInputElement).value = ''
  })
  const fontUploadZone = el('label', { for: 'font-upload-input', class: 'upload-zone' },
    fontFileInput,
    el('span', {}, 'Click or drop a .ttf / .otf / .woff / .woff2 font'),
  )
  fontUploadZone.addEventListener('dragover', e => { e.preventDefault(); fontUploadZone.classList.add('drag-over') })
  fontUploadZone.addEventListener('dragleave', () => fontUploadZone.classList.remove('drag-over'))
  fontUploadZone.addEventListener('drop', e => {
    e.preventDefault()
    fontUploadZone.classList.remove('drag-over')
    const f = (e as DragEvent).dataTransfer?.files[0]
    if (f) void handleFontUpload(f)
  })

  async function handleFontUpload(file: File): Promise<void> {
    const name = file.name.replace(/\.[^.]+$/, '').trim()
    if (!name) { showStatus('Font upload failed: could not determine a font name.', false); return }
    try {
      const dataURL = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(reader.result as string)
        reader.onerror = () => reject(reader.error ?? new Error('Could not read file.'))
        reader.readAsDataURL(file)
      })
      const font: FontInfo = { name, path: dataURL }
      await loadFont(font)
      state.fonts = [...state.fonts.filter(f => f.name !== name), font]
      saveCustomFont(font)
      try {
        await api.publishFont(font)
        showStatus(`Font "${name}" uploaded and shared. Pick it from the Font dropdown on the Label tab.`, true)
      } catch (e) {
        // Still usable locally (loaded above + cached), just not shared to other browsers yet.
        showStatus(`Font "${name}" uploaded locally, but could not be shared (MQTT: ${e instanceof Error ? e.message : String(e)}).`, false)
      }
    } catch (e) {
      showStatus('Font upload failed: ' + (e instanceof Error ? e.message : String(e)), false)
    }
  }

  root.append(section('Fonts', fontUploadZone))

  editorWrap.append(
    section('General',
      el('div', { class: 'select-row' }, el('label', {}, 'app.name'), appNameInput),
      el('div', { class: 'select-row' }, el('label', {}, 'app.subtitle'), appSubtitleInput),
      el('div', { class: 'select-row' }, el('label', {}, 'app.zplExample'), zplExampleInput),
      el('label', { class: 'toggle' }, zplRawEnabledInput, el('span', { class: 'toggle-text' }, 'app.zplRawEnabled')),
      el('label', { class: 'toggle' }, cableEnabledInput, el('span', { class: 'toggle-text' }, 'app.cableLabelEnabled')),
      el('div', { class: 'select-row' }, el('label', {}, 'app.cableLabelZPLTemplate'), cableTemplateInput),
      el('div', { class: 'select-row' }, el('label', {}, 'mqttSettingsPassword'), settingsPwdInput),
    ),
    section('MQTT',
      el('div', { class: 'select-row' }, el('label', {}, 'mqtt.brokerURL'), mqttBrokerInput),
      el('div', { class: 'select-row' }, el('label', {}, 'mqtt.username'), mqttUserInput),
      el('div', { class: 'select-row' }, el('label', {}, 'mqtt.password'), mqttPasswordInput),
      el('p', { class: 'config-hint' }, 'Topics are fixed: /<printername>/status/ and /<printername>/command/'),
      el('div', { class: 'select-row' }, el('label', {}, 'mqtt.clientIdPrefix'), mqttClientPrefixInput),
      el('div', { class: 'select-row' }, el('label', {}, 'mqtt.discoveryWaitMs'), mqttDiscoveryWaitInput),
    ),
    section('Apply',
      el('div', { class: 'btn-row' }, applyBtn),
    ),
  )

  if (!(settingsPassword ?? '')) {
    unlockWrap.classList.add('hidden')
    editorWrap.classList.remove('hidden')
  }

  root.append(unlockWrap, editorWrap, statusEl)
  return root
}

// ── Build Text Controls panel ────────────────────────────────────────────────

function buildFontPicker(onChange: (name: string) => void): HTMLElement {
  let current = state.fontName || '(default)'

  const labelEl = el('span', { class: 'font-picker-label' })
  const listEl  = el('div',  { class: 'font-picker-list hidden' })
  const root    = el('div',  { class: 'font-picker' }, labelEl, listEl)

  // Recomputed on every open so fonts uploaded via the Settings tab
  // (which mutate state.fonts after this picker is first built) show up
  // without needing to rebuild the whole panel.
  function getFonts(): FontInfo[] {
    const fonts = [{ name: '(default)', path: '' }, ...state.fonts]
    if (!fonts.some(f => f.name === '5x5Tami')) {
      fonts.push({ name: '5x5Tami', path: 'builtin' })
    }
    return fonts
  }

  function updateLabel(): void {
    labelEl.textContent = current
    const f = getFonts().find(f => f.name === current)
    ;(labelEl as HTMLElement).style.fontFamily = (f && f.path) ? `"${current}", sans-serif` : ''
  }

  function renderList(): void {
    listEl.innerHTML = ''
    getFonts().forEach(f => {
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
  }

  function close(): void { listEl.classList.add('hidden') }
  function open(): void  { renderList(); listEl.classList.remove('hidden'); listEl.scrollTop = 0 }

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
      const rot = slider('Rotate', -180, 180, 15, state.rotateText, v => { state.rotateText = v; schedulePreview() })
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
    select('Rotate', ['0', '90', '180', '270'] as const, String(state.barcodeRotate) as '0', v => { state.barcodeRotate = parseInt(v); schedulePreview() }),
    el('div', { class: 'btn-row' }, generateBtn, clearBtn),
  )
}

// ── Build Raw ZPL tab ────────────────────────────────────────────────────────

function buildZPLTab(): HTMLElement {
  const isZplCompatible = (type: string): boolean => {
    const t = type.toLowerCase()
    return t === 'zpl' || t === 'zebra'
  }

  let zplPrinters = state.printers.filter(p => isZplCompatible(p.type))
  let selectedZPLIndex = zplPrinters.length > 0 ? zplPrinters[0].index : -1

  // Printer selector (ZPL-only)
  const printerSel = el('select', { class: 'printer-select' })
  const renderZPLPrinterOptions = (): void => {
    printerSel.innerHTML = ''
    if (!zplPrinters.length) {
      printerSel.append(el('option', { value: '-1' }, '(no ZPL printers configured)'))
      selectedZPLIndex = -1
      return
    }
    zplPrinters.forEach(p => {
      const shape = p.label.length > 0
        ? `${p.label.width}×${p.label.length}mm`
        : `${p.label.width}mm endless`
      const serial = p.serial ? ` · ${p.serial}` : ''
      const opt = el('option', { value: String(p.index) }, `${p.name}${serial} · ${p.label.isRound ? 'ø' : ''}${shape}`)
      if (p.index === selectedZPLIndex) opt.setAttribute('selected', '')
      printerSel.append(opt)
    })
  }
  renderZPLPrinterOptions()

  const unsubscribe = api.subscribeMQTTPrinters((printers) => {
    const selectedName = zplPrinters.find(p => p.index === selectedZPLIndex)?.name ?? ''
    zplPrinters = printers.filter(p => isZplCompatible(p.type))
    const next = zplPrinters.find(p => p.name === selectedName)
    selectedZPLIndex = next ? next.index : (zplPrinters[0]?.index ?? -1)
    renderZPLPrinterOptions()
    scheduleZPLPreview()
  })
  window.addEventListener('beforeunload', () => unsubscribe(), { once: true })
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
  async function runZPLPreview(): Promise<void> {
    if (selectedZPLIndex < 0) return
    try {
      const url = await api.previewZPL(selectedZPLIndex, state.rawZPL)
      ;(previewImg as HTMLImageElement).src = url
      previewImg.classList.remove('hidden')
      previewWrap.querySelector('.zpl-preview-placeholder')?.classList.add('hidden')

      // Shape the preview to match the label format
      const printer = zplPrinters.find(p => p.index === selectedZPLIndex)
      if (printer) {
        ;(previewWrap as HTMLElement).style.borderRadius = printer.label.isRound ? '50%' : '0'
        ;(previewWrap as HTMLElement).style.overflow = 'hidden'
        ;(previewImg as HTMLElement).style.width = ''
        ;(previewImg as HTMLElement).style.height = ''
        ;(previewImg as HTMLElement).style.maxWidth = '100%'
        ;(previewImg as HTMLElement).style.maxHeight = '100%'
        ;(previewImg as HTMLElement).style.objectFit = 'contain'
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      showStatus('Preview failed: ' + msg, false, 0)
    }
  }
  function scheduleZPLPreview(): void {
    if (zplPreviewTimer !== null) clearTimeout(zplPreviewTimer)
    zplPreviewTimer = window.setTimeout(runZPLPreview, 600)
  }

  const textarea = el('textarea', { class: 'zpl-textarea' })
  ;(textarea as HTMLTextAreaElement).spellcheck = false
  ;(textarea as HTMLTextAreaElement).value = state.rawZPL
  textarea.addEventListener('input', () => {
    state.rawZPL = (textarea as HTMLTextAreaElement).value
  })

  const previewBtn = btn('Preview', 'btn btn-secondary btn-large', () => { void runZPLPreview() })

  const sendBtn = btn('Send to Printer', 'btn btn-primary btn-large', async () => {
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

  return el('div', { class: 'tab-content' },
    el('div', { class: 'zpl-toolbar' },
      printerSel,
      previewBtn,
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
  const isZplCompatible = (type: string): boolean => {
    const t = type.toLowerCase()
    return t === 'zpl' || t === 'zebra'
  }

  let zplPrinters = state.printers.filter(p => isZplCompatible(p.type))
  let selectedZPLIndex = zplPrinters.length > 0 ? zplPrinters[0].index : -1

  // Printer selector (ZPL-only)
  const printerSel = el('select', { class: 'printer-select' })
  const renderCablePrinterOptions = (): void => {
    printerSel.innerHTML = ''
    if (!zplPrinters.length) {
      printerSel.append(el('option', { value: '-1' }, '(no ZPL printers configured)'))
      selectedZPLIndex = -1
      return
    }
    zplPrinters.forEach(p => {
      const shape = p.label.length > 0
        ? `${p.label.width}×${p.label.length}mm`
        : `${p.label.width}mm endless`
      const serial = p.serial ? ` · ${p.serial}` : ''
      const opt = el('option', { value: String(p.index) }, `${p.name}${serial} · ${p.label.isRound ? 'ø' : ''}${shape}`)
      if (p.index === selectedZPLIndex) opt.setAttribute('selected', '')
      printerSel.append(opt)
    })
  }
  renderCablePrinterOptions()

  const unsubscribe = api.subscribeMQTTPrinters((printers) => {
    const selectedName = zplPrinters.find(p => p.index === selectedZPLIndex)?.name ?? ''
    zplPrinters = printers.filter(p => isZplCompatible(p.type))
    const next = zplPrinters.find(p => p.name === selectedName)
    selectedZPLIndex = next ? next.index : (zplPrinters[0]?.index ?? -1)
    renderCablePrinterOptions()
  })
  window.addEventListener('beforeunload', () => unsubscribe(), { once: true })
  printerSel.addEventListener('change', () => {
    selectedZPLIndex = parseInt((printerSel as HTMLSelectElement).value)
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
  const previewImg = el('img', { class: 'zpl-inline-preview', alt: 'Cable label preview' })
  const previewWrap = el('div', { class: 'zpl-preview-wrap' },
    el('div', { class: 'zpl-preview-placeholder' }, 'Preview will appear here'),
    previewImg,
  )

  async function runPreview(): Promise<void> {
    if (selectedZPLIndex < 0) return
    try {
      const url = await api.previewZPL(selectedZPLIndex, generateZPL())
      ;(previewImg as HTMLImageElement).src = url
      previewImg.classList.remove('hidden')
      previewWrap.querySelector('.zpl-preview-placeholder')?.classList.add('hidden')
      const printer = zplPrinters.find(p => p.index === selectedZPLIndex)
      if (printer) {
        ;(previewWrap as HTMLElement).style.borderRadius = printer.label.isRound ? '50%' : '0'
        ;(previewWrap as HTMLElement).style.overflow = 'hidden'
        ;(previewImg as HTMLElement).style.maxWidth = '100%'
        ;(previewImg as HTMLElement).style.maxHeight = '100%'
        ;(previewImg as HTMLElement).style.objectFit = 'contain'
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      showStatus('Preview failed: ' + msg, false, 0)
    }
  }

  // Text inputs
  const textInput1 = el('input', { type: 'text', class: 'text-input', placeholder: 'Line 1 (max 15 chars)…', maxlength: '15' })
  const textInput2 = el('input', { type: 'text', class: 'text-input', placeholder: 'Line 2 (max 15 chars)…', maxlength: '15' })

  // Generate ZPL function
  function generateZPL(): string {
    const input1 = (textInput1 as HTMLInputElement).value || ''
    const input2 = (textInput2 as HTMLInputElement).value || ''
    return state.cableLabelZPLTemplate
      .replace(/\$input1\$/g, input1)
      .replace(/\$input2\$/g, input2)
  }

  // ZPL display (read-only)
  const zplDisplay = el('textarea', { class: 'zpl-textarea', readonly: '' })
  ;(zplDisplay as HTMLTextAreaElement).spellcheck = false
  ;(zplDisplay as HTMLTextAreaElement).value = generateZPL()

  let zplStatusUpdateTimer: number | null = null

  function updateZPLDisplay(): void {
    if (zplStatusUpdateTimer !== null) clearTimeout(zplStatusUpdateTimer)
    zplStatusUpdateTimer = window.setTimeout(() => {
      ;(zplDisplay as HTMLTextAreaElement).value = generateZPL()
    }, 100)
  }

  textInput1.addEventListener('input', () => {
    updateZPLDisplay()
  })

  textInput2.addEventListener('input', () => {
    updateZPLDisplay()
  })

  const previewBtn = btn('Preview', 'btn btn-secondary btn-large', () => { void runPreview() })
  const sendBtn = btn('Send to Printer', 'btn btn-primary btn-large', async () => {
    if (selectedZPLIndex < 0) { showStatus('No ZPL printer available.', false); return }
    const input1 = (textInput1 as HTMLInputElement).value.trim()
    const input2 = (textInput2 as HTMLInputElement).value.trim()
    if (!input1 && !input2) { showStatus('Enter at least one line of text.', false); return }
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

  // Trigger initial display update
  updateZPLDisplay()

  return el('div', { class: 'tab-content' },
    el('div', { class: 'zpl-toolbar' },
      printerSel,
      previewBtn,
      sendBtn,
    ),
    statusEl,
    textInput1,
    textInput2,
    el('div', { class: 'zpl-editor-grid' },
      zplDisplay,
      previewWrap,
    ),
  )
}

// ── Build ESP32 Flasher tab ────────────────────────────────────────────────

function buildESP32FlasherTab(): HTMLElement {
  const root = el('div', { class: 'tab-content esp32-flasher-tab' })
  const boardSelect = el('select', { class: 'text-input' }) as HTMLSelectElement
  const statusEl = el('div', { class: 'status-msg hidden' })
  const directFlashWrap = el('div', { class: 'esp32-direct-flash-wrap hidden' })
  const installEl = document.createElement('esp-web-install-button') as HTMLElement
  const installButton = btn('Flash Stikka Firmware', 'btn btn-primary btn-large', () => {})
  installButton.setAttribute('slot', 'activate')
  installEl.append(installButton)
  directFlashWrap.append(installEl)

  function updateCommandAndManifest(): void {
    const envName = boardSelect.value
    const manifestPath = boardSelect.selectedOptions[0]?.getAttribute('data-manifest') ?? ''
    boardSelect.setAttribute('data-manifest', manifestPath)
    const hasManifest = Boolean(manifestPath)
    if (hasManifest) {
      const manifestURL = new URL(manifestPath, window.location.href).toString()
      installEl.setAttribute('manifest', manifestURL)
      directFlashWrap.classList.remove('hidden')
    } else {
      installEl.removeAttribute('manifest')
      directFlashWrap.classList.add('hidden')
    }
    if (hasManifest) {
      statusEl.textContent = `Ready: ${envName}`
      statusEl.className = 'status-msg status-ok'
      statusEl.classList.remove('hidden')
    }
  }

  boardSelect.addEventListener('change', updateCommandAndManifest)

  const firmwareIndexURL = `${import.meta.env.BASE_URL}firmware/index.json`
  fetch(firmwareIndexURL, { cache: 'no-store' })
    .then(async res => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return res.json() as Promise<{
        environments?: Array<{ env: string; basePath: string; manifest?: string }>
      }>
    })
    .then(index => {
      boardSelect.innerHTML = ''
      const envs = index.environments ?? []
      if (!envs.length) {
        throw new Error('No firmware environments found in index.json')
      }
      for (const entry of envs) {
        const manifestRel = `${import.meta.env.BASE_URL}firmware/${entry.env}/${entry.manifest ?? 'manifest.json'}`
        const option = el('option', { value: entry.env, 'data-manifest': manifestRel }, entry.env)
        boardSelect.append(option)
      }
      updateCommandAndManifest()
    })
    .catch(err => {
      statusEl.textContent = `Firmware index missing. Run build-firmware first. (${String(err)})`
      statusEl.className = 'status-msg status-err'
      statusEl.classList.remove('hidden')
      boardSelect.innerHTML = ''
      boardSelect.append(el('option', { value: 'esp32dev' }, 'esp32dev'))
      updateCommandAndManifest()
      directFlashWrap.classList.add('hidden')
    })

  root.append(
    section('ESP32 Stikka Firmware',
      el('div', { class: 'select-row' }, el('label', {}, 'Board profile'), boardSelect),
      statusEl,
      directFlashWrap,
      el('p', {}, 'Direct flashing works in Chromium-based browsers over HTTPS or localhost.'),
      el('p', {}, 'After first boot, if Wi-Fi is not configured or cannot connect, the firmware starts a fallback access point.'),
      el('p', {},
        'Fallback AP SSID: ',
        el('code', {}, 'Stikka-<chip suffix>'),
        ' | Password: ',
        el('code', {}, 'stikkaesp32'),
        ' | AP IP: ',
        el('code', {}, '192.168.4.1'),
      ),
    ),
  )

  return root
}

// ── Build About tab ───────────────────────────────────────────────────────────

function buildAboutTab(): HTMLElement {
  const statsEl = el('div', { class: 'about-stats' })
  const readmeTitleEl = el('h3', {}, 'README')
  const readmeEl = el('div', { class: 'about-readme' })
  const root = el('div', { class: 'tab-content' }, statsEl, readmeTitleEl, readmeEl)

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
    const contentEl = el('div')
    contentEl.innerHTML = html
    readmeEl.append(contentEl)
  }).catch(() => {
    readmeEl.append(
      el('p', { class: 'status-err' }, 'Could not load README.')
    )
  })

  return root
}
// ── Main app builder ─────────────────────────────────────────────────────────

export async function initApp(
  appEl: HTMLElement,
  initialState: AppState,
  appName = 'Gostikka',
  appSubtitle = '',
  zplRawEnabled = true,
  cableLabelEnabled = false,
  mqttSettingsPassword?: string,
): Promise<void> {
  state = initialState
  await loadAllFonts(state.fonts)

  const printerLabel = (p: PrinterInfo): string => {
    const shape = p.label.length > 0
      ? `${p.label.width}×${p.label.length}mm`
      : `${p.label.width}mm endless`
    const serial = p.serial ? ` · ${p.serial}` : ''
    return `${p.name}${serial} · ${p.label.isRound ? 'ø' : ''}${shape}`
  }

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
    if (f) void handleFileUpload(f)
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
    if (f) void handleFileUpload(f)
  })

  // ── Printer selector ──
  const printerSel = el('select', { class: 'printer-select' })
  const mqttStateEl = el('div', { class: 'status-msg hidden' })

  function renderPrinterOptions(): void {
    printerSel.innerHTML = ''
    if (!state.printers.length) {
      printerSel.append(el('option', { value: '-1' }, '(no printers configured)'))
      state.selectedPrinterIndex = -1
      return
    }
    state.printers.forEach((p, i) => {
      const o = el('option', { value: String(i) }, printerLabel(p))
      if (i === state.selectedPrinterIndex) o.setAttribute('selected', '')
      printerSel.append(o)
    })
  }

  function updateMQTTStateHint(): void {
    const mqttConn = api.getMQTTConnectionState()
    if (!mqttConn.connected) {
      const reason = mqttConn.lastError ? ` (${mqttConn.lastError})` : ''
      mqttStateEl.textContent = `MQTT broker disconnected${reason}`
      mqttStateEl.className = 'status-msg status-err'
      mqttStateEl.classList.remove('hidden')
      return
    }

    const selectedPrinter = state.printers[state.selectedPrinterIndex]
    if (selectedPrinter && api.isDummyPrinter(selectedPrinter.name)) {
      mqttStateEl.textContent = 'Using frontend dummy printer fallback. Jobs will publish over MQTT without discovered printer status.'
      mqttStateEl.className = 'status-msg status-ok'
      mqttStateEl.classList.remove('hidden')
      return
    }

    const meta = api.getMQTTPrinterMetaByIndex(state.selectedPrinterIndex)
    if (!meta) {
      mqttStateEl.textContent = 'Waiting for printer status on /status/<printername> ...'
      mqttStateEl.className = 'status-msg status-err'
      mqttStateEl.classList.remove('hidden')
      return
    }
    const mode = meta.online ? (meta.busy ? 'busy' : 'online') : 'offline'
    const extra = meta.lastError ? ` · ${meta.lastError}` : ''
    mqttStateEl.textContent = `MQTT printer state: ${mode}${extra}`
    mqttStateEl.className = 'status-msg ' + (meta.online ? 'status-ok' : 'status-err')
    mqttStateEl.classList.remove('hidden')
  }

  renderPrinterOptions()

  printerSel.addEventListener('change', () => {
    state.selectedPrinterIndex = parseInt((printerSel as HTMLSelectElement).value)
    updateMQTTStateHint()
    schedulePreview()
  })

  const printerSubscription = api.subscribeMQTTPrinters((printers) => {
    const currentName = state.printers[state.selectedPrinterIndex]?.name ?? ''
    state.printers = printers

    if (!printers.length) {
      state.selectedPrinterIndex = -1
    } else {
      const match = printers.findIndex(p => p.name === currentName)
      state.selectedPrinterIndex = match >= 0 ? match : 0
    }

    renderPrinterOptions()
    updateMQTTStateHint()
    schedulePreview()
  })

  window.addEventListener('beforeunload', () => printerSubscription(), { once: true })
  updateMQTTStateHint()

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
    ...(cableLabelEnabled ? [{ name: 'Cable Label', panel: el('div', { class: 'tab-panel', id: 'tab-cable' }) }] : []),
    { name: 'About', panel: el('div', { class: 'tab-panel', id: 'tab-about' }) },
    { name: 'ESP32 Flasher', panel: el('div', { class: 'tab-panel', id: 'tab-esp32-flasher' }) },
    { name: 'Settings', panel: el('div', { class: 'tab-panel', id: 'tab-settings' }) },
  ]
  const rightTabNames = new Set(['ESP32 Flasher', 'Settings'])
  const firstRightTabIndex = allTabs.findIndex(t => rightTabNames.has(t.name))
  const tabBtns: HTMLButtonElement[] = []
  const tabPanels = allTabs.map(t => t.panel)

  allTabs.forEach(({ name }, i) => {
    const isRightGroup = rightTabNames.has(name)
    const isRightStart = i === firstRightTabIndex
    const b = el('button', {
      class: 'tab-btn'
        + (i === 0 ? ' active' : '')
        + (isRightGroup ? ' tab-btn-right-group' : '')
        + (isRightStart ? ' tab-btn-right' : ''),
    }, name)
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
    mqttStateEl,
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
  if (cableLabelEnabled) getPanel('tab-cable').append(buildCableLabelTab())
  getPanel('tab-esp32-flasher').append(buildESP32FlasherTab())
  getPanel('tab-about').append(buildAboutTab())
  getPanel('tab-settings').append(buildSettingsTab(() => {
    updateMQTTStateHint()
    schedulePreview()
  }, mqttSettingsPassword))

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

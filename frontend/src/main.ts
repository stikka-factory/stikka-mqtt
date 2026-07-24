import './layout.css'
import './style.css'
import { defaultState } from './types'
import { fetchAppInfo, fetchPrinters, fetchFonts, initTransport } from './mqtt-api'
import { initApp } from './ui'
import { loadStaticModeConfig, loadCustomFonts } from './static-config'

async function main(): Promise<void> {
  const appEl = document.getElementById('app')
  if (!appEl) return

  appEl.textContent = 'Loading…'

  const state = defaultState()
  const staticConfig = await loadStaticModeConfig()
  if (!staticConfig) {
    appEl.textContent = 'Missing frontend/public/config.json for MQTT mode.'
    return
  }

  try {
    await initTransport(staticConfig)
  } catch (e) {
    console.warn('Could not initialize MQTT transport:', e)
    appEl.textContent = 'Could not initialize MQTT transport. Check config.json MQTT settings.'
    return
  }

  let appName = 'Gostikka'
  let appSubtitle = ''
  let zplRawEnabled = true
  let cableLabelEnabled = false

  try {
    const [info, printers, fonts] = await Promise.all([fetchAppInfo(), fetchPrinters(), fetchFonts()])
    appName = info.name
    appSubtitle = info.subtitle
    zplRawEnabled = info.zplRawEnabled
    cableLabelEnabled = info.cableLabelEnabled
    if (info.zplExample) state.rawZPL = info.zplExample
    if (info.cableLabelZPLTemplate) state.cableLabelZPLTemplate = info.cableLabelZPLTemplate
    state.printers = printers
    const customFonts = loadCustomFonts()
    state.fonts = [...fonts.filter(f => !customFonts.some(c => c.name === f.name)), ...customFonts]
    if (fonts.length > 0) state.fontName = fonts[0].name
  } catch (e) {
    console.warn('Could not load config from server:', e)
  }

  document.title = appName
  await initApp(
    appEl,
    state,
    appName,
    appSubtitle,
    zplRawEnabled,
    cableLabelEnabled,
  )
}

main()

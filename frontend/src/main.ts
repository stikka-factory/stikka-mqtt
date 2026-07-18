import './layout.css'
import './style.css'
import { defaultState } from './types'
import { fetchAppInfo, fetchPrinters, fetchFonts, initTransport, isMQTTMode } from './api'
import { initApp } from './ui'
import { loadStaticModeConfig } from './static-config'

async function main(): Promise<void> {
  const appEl = document.getElementById('app')
  if (!appEl) return

  appEl.textContent = 'Loading…'

  const state = defaultState()
  const staticConfig = await loadStaticModeConfig()
  try {
    await initTransport(staticConfig)
  } catch (e) {
    console.warn('Could not initialize selected transport:', e)
    await initTransport(null)
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
    state.fonts = fonts
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
    isMQTTMode(),
    staticConfig?.mqttSettingsPassword,
  )
}

main()

import './style.css'
import { defaultState } from './types'
import { fetchAppInfo, fetchPrinters, fetchFonts } from './api'
import { initApp } from './ui'

async function main(): Promise<void> {
  const appEl = document.getElementById('app')
  if (!appEl) return

  appEl.textContent = 'Loading…'

  const state = defaultState()
  let appName = 'Gostikka'
  let appSubtitle = ''
  let zplRawEnabled = true

  try {
    const [info, printers, fonts] = await Promise.all([fetchAppInfo(), fetchPrinters(), fetchFonts()])
    appName = info.name
    appSubtitle = info.subtitle
    zplRawEnabled = info.zplRawEnabled
    if (info.zplExample) state.rawZPL = info.zplExample
    state.printers = printers
    state.fonts = fonts
    if (fonts.length > 0) state.fontName = fonts[0].name
  } catch (e) {
    console.warn('Could not load config from server:', e)
  }

  document.title = appName
  await initApp(appEl, state, appName, appSubtitle, zplRawEnabled)
}

main()

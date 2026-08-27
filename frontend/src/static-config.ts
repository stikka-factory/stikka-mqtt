import type { FontInfo, StaticModeConfig } from './types'

const CUSTOM_FONTS_KEY = 'stikka_custom_fonts'
const THEME_KEY = 'stikka_theme'

export type Theme = 'light' | 'dark' | 'haxor'

function normalize(raw: Partial<StaticModeConfig>): StaticModeConfig {
  return {
    mode: 'mqtt',
    app: {
      name: raw.app?.name ?? 'Gostikka',
      subtitle: raw.app?.subtitle ?? '',
      zplExample: raw.app?.zplExample ?? '^XA\n^CFA,30\n^FO50,20\n^FDHello ZPL^FS\n^XZ',
      zplRawEnabled: raw.app?.zplRawEnabled ?? true,
      cableLabelEnabled: raw.app?.cableLabelEnabled ?? false,
      cableLabelZPLTemplate: raw.app?.cableLabelZPLTemplate,
    },
    mqtt: {
      brokerURL: raw.mqtt?.brokerURL ?? '',
      username: raw.mqtt?.username,
      password: raw.mqtt?.password,
      clientIdPrefix: raw.mqtt?.clientIdPrefix ?? 'stikka-web',
      discoveryWaitMs: raw.mqtt?.discoveryWaitMs ?? 1500,
    },
    supabase: {
      url: raw.supabase?.url ?? '',
      anonKey: raw.supabase?.anonKey ?? '',
    },
  }
}

// config.json is written at deploy time by .github/workflows/deploy-pages.yml
// from repo Variables/Secrets, and is identical for every visitor of the
// deployed site. There's no in-app editor for it (only fonts are runtime/
// globally editable, via Supabase -- see publishFont() in mqtt-api.ts);
// changing app.*/mqtt.*/supabase.* means changing repo Variables/Secrets and
// redeploying (see CLAUDE.md).
export async function loadStaticModeConfig(): Promise<StaticModeConfig | null> {
  const url = `${import.meta.env.BASE_URL}config.json`
  try {
    const res = await fetch(url, { cache: 'no-store' })
    if (!res.ok) return null
    const json = await res.json() as Partial<StaticModeConfig>
    return normalize(json)
  } catch {
    return null
  }
}

// Fonts uploaded via the Fonts tab are shared globally via Supabase (see
// publishFont() in mqtt-api.ts). This local copy is just a fallback cache so
// the uploading browser still sees its own fonts immediately/offline,
// before or without a network round trip.
export function loadCustomFonts(): FontInfo[] {
  try {
    const raw = window.localStorage.getItem(CUSTOM_FONTS_KEY)
    if (!raw) return []
    return JSON.parse(raw) as FontInfo[]
  } catch {
    return []
  }
}

export function saveCustomFont(font: FontInfo): void {
  const fonts = loadCustomFonts().filter(f => f.name !== font.name)
  fonts.push(font)
  window.localStorage.setItem(CUSTOM_FONTS_KEY, JSON.stringify(fonts))
}

// Theme preference. Resolving "no choice made yet" against the OS
// preference happens in index.html's inline bootstrap script (it has to run
// before first paint, earlier than any bundled module) -- saveTheme() here
// just needs to agree with it on the storage key and value shape.
export function saveTheme(theme: Theme): void {
  window.localStorage.setItem(THEME_KEY, theme)
}

// Themes are swappable stylesheets, not CSS rules gated on an attribute
// selector (see public/themes/*.css) -- switching theme means pointing the
// <link> at a different file. index.html's inline bootstrap script creates
// that <link> before first paint; this just repoints it for a later,
// in-app change.
export function applyTheme(theme: Theme): void {
  document.documentElement.setAttribute('data-theme', theme)
  let link = document.getElementById('theme-link') as HTMLLinkElement | null
  if (!link) {
    link = document.createElement('link')
    link.id = 'theme-link'
    link.rel = 'stylesheet'
    document.head.appendChild(link)
  }
  link.href = `${import.meta.env.BASE_URL}themes/${theme}.css`
}

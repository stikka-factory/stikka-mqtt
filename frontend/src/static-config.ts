import type { StaticModeConfig } from './types'

const MQTT_OVERRIDE_KEY = 'stikka_mqtt_override'
const STATIC_CONFIG_OVERRIDE_KEY = 'stikka_static_config_override'

function normalize(raw: Partial<StaticModeConfig>): StaticModeConfig {
  return {
    mode: raw.mode ?? 'backend',
    app: {
      name: raw.app?.name ?? 'Gostikka',
      subtitle: raw.app?.subtitle ?? '',
      zplExample: raw.app?.zplExample ?? '^XA\n^CFA,30\n^FO50,20\n^FDHello ZPL^FS\n^XZ',
      zplRawEnabled: raw.app?.zplRawEnabled ?? true,
      cableLabelEnabled: raw.app?.cableLabelEnabled ?? false,
      cableLabelZPLTemplate: raw.app?.cableLabelZPLTemplate,
    },
    mqtt: raw.mqtt,
    mqttSettingsPassword: raw.mqttSettingsPassword,
    fonts: raw.fonts ?? [],
    printers: raw.printers ?? [],
  }
}

export async function loadStaticModeConfig(): Promise<StaticModeConfig | null> {
  const url = `${import.meta.env.BASE_URL}config.json`
  try {
    const res = await fetch(url, { cache: 'no-store' })
    if (!res.ok) return null
    const json = await res.json() as Partial<StaticModeConfig>
    const normalized = normalize(json)

    const fullOverride = loadStaticConfigOverride()
    if (fullOverride) {
      const merged: Partial<StaticModeConfig> = {
        ...normalized,
        ...fullOverride,
        app: {
          ...normalized.app,
          ...fullOverride.app,
        },
      }

      const mergedMqtt = {
        ...(normalized.mqtt ?? {}),
        ...(fullOverride.mqtt ?? {}),
      }
      if (typeof mergedMqtt.brokerURL === 'string' && mergedMqtt.brokerURL.length > 0) {
        merged.mqtt = mergedMqtt as NonNullable<StaticModeConfig['mqtt']>
      }

      return normalize(merged)
    }

    const override = loadMQTTOverride()
    if (override && normalized.mode === 'mqtt' && normalized.mqtt) {
      normalized.mqtt = {
        ...normalized.mqtt,
        ...override,
      }
    }
    return normalized
  } catch {
    return null
  }
}

export function loadMQTTOverride(): Partial<NonNullable<StaticModeConfig['mqtt']>> | null {
  try {
    const raw = window.localStorage.getItem(MQTT_OVERRIDE_KEY)
    if (!raw) return null
    return JSON.parse(raw) as Partial<NonNullable<StaticModeConfig['mqtt']>>
  } catch {
    return null
  }
}

export function saveMQTTOverride(override: Partial<NonNullable<StaticModeConfig['mqtt']>>): void {
  window.localStorage.setItem(MQTT_OVERRIDE_KEY, JSON.stringify(override))
}

export function clearMQTTOverride(): void {
  window.localStorage.removeItem(MQTT_OVERRIDE_KEY)
}

export function loadStaticConfigOverride(): StaticModeConfig | null {
  try {
    const raw = window.localStorage.getItem(STATIC_CONFIG_OVERRIDE_KEY)
    if (!raw) return null
    return normalize(JSON.parse(raw) as Partial<StaticModeConfig>)
  } catch {
    return null
  }
}

export function saveStaticConfigOverride(config: StaticModeConfig): void {
  window.localStorage.setItem(STATIC_CONFIG_OVERRIDE_KEY, JSON.stringify(config))
}

export function clearStaticConfigOverride(): void {
  window.localStorage.removeItem(STATIC_CONFIG_OVERRIDE_KEY)
}

// Shared TypeScript interfaces for Gostikka

export interface AppInfo {
  name: string
  subtitle: string
  zplExample: string
  zplRawEnabled: boolean
  cableLabelEnabled: boolean
  cableLabelZPLTemplate?: string
  textOverlayEnabled: boolean
}

export interface StaticModeConfig {
  mode: 'mqtt'
  app: AppInfo
  mqtt: MQTTFrontendConfig
  supabase: SupabaseFrontendConfig
}

export interface MQTTFrontendConfig {
  brokerURL: string
  username?: string
  password?: string
  clientIdPrefix?: string
  discoveryWaitMs?: number
}

// Backs fonts/print-stats/printer-discovery storage (see supabase-client.ts
// and supabase/schema.sql) -- MQTT is still the only channel the ESP32
// firmware speaks, so it remains the ingestion path for printer status, but
// no longer the storage layer for any of these three.
export interface SupabaseFrontendConfig {
  url: string
  anonKey: string
}

export interface PrinterStatusMessage {
  printer_name?: string
  name?: string
  online?: boolean
  busy?: boolean
  // Only present on full status snapshots (buildStatusJson() in main.cpp),
  // never on per-job status updates (publishJobStatus()) -- both publish to
  // the same /<printer>/status/ topic, so this is what tells them apart.
  phase?: string
  type?: string
  serial?: string
  location?: string
  dpi?: number
  label?: {
    width?: number
    length?: number
    isRound?: boolean
    verticalOffset?: number
    cut?: boolean
  }
  capabilities?: {
    type?: string
    dpi?: number
    label?: {
      width?: number
      length?: number
      isRound?: boolean
      verticalOffset?: number
      cut?: boolean
    }
    // Whether this printer's firmware supports the :Z64:/:B64: compressed
    // ^GF graphic field syntax -- not every ZPL-compatible engine does, so
    // this is opt-in per printer rather than assumed. See zpl-image.ts.
    zplCompression?: boolean
    // Brother QL raster protocol knobs -- the frontend now builds the whole
    // raster byte stream itself (zpl-image.ts's imageDataURLToQLRasterBase64),
    // so it needs these per-printer instead of the firmware. Only meaningful
    // for type "ql"/"brother_ql"; see esp32/src/config.h for what each means.
    qlPrintheadPx?: number
    qlInvalidateBytes?: number
    qlAutoCut?: boolean
    qlFeedMarginDots?: number
    qlRightMarginDots?: number
    // Seiko SLP raster protocol knobs -- same rationale as the ql* fields
    // above (frontend builds the whole raster byte stream itself, see
    // zpl-image.ts's imageDataURLToSeikoRasterBase64). Only meaningful for
    // type "seiko"/"seiko_slp". Firmware-side support doesn't exist yet
    // (stikka-esp32 is mid-refactor to a runtime-selectable protocol model);
    // these fields are wired up on the frontend ahead of that so printers
    // reporting them once it lands need no further frontend changes.
    seikoMaxDots?: number
    seikoDensity?: number
    seikoSpeed?: number
  }
  last_error?: string
}

export interface PrinterInfo {
  index: number
  name: string
  serial: string
  location: string
  type: string
  dpi: number
  label: {
    width: number         // mm
    length: number        // mm (0 = continuous)
    isRound: boolean
    verticalOffset: number
    cut: boolean
  }
  zplCompressionSupported: boolean
  // Brother QL raster protocol knobs (type "ql"/"brother_ql" only) -- see
  // PrinterStatusMessage.capabilities above.
  qlPrintheadPx: number
  qlInvalidateBytes: number
  qlAutoCut: boolean
  qlFeedMarginDots: number
  qlRightMarginDots: number
  // Seiko SLP raster protocol knobs (type "seiko"/"seiko_slp" only) -- see
  // PrinterStatusMessage.capabilities above.
  seikoMaxDots: number
  seikoDensity: number
  seikoSpeed: number
}

export interface FontInfo {
  name: string
  // Built-in fonts: a real path like /fonts/SomeFont.ttf. Uploaded fonts: a
  // public Supabase Storage URL (see uploadSupabaseFont() in
  // supabase-client.ts) -- never an embedded data: URL, so this never grows
  // unbounded the way the old MQTT-retained font blob did.
  path: string
}

export interface PrintStats {
  printed_total: number
  printed_cats: number
  printed_dogs: number
  printed_dinos: number
  printed_uploaded_images: number
  printed_webcam_images: number
  printed_without_image: number
}

export type ImageSourceKind = 'none' | 'cat' | 'dog' | 'dino' | 'upload' | 'webcam'

export interface ScannedPrinter {
  name: string
  type: string
  connection: string
  serial: string
  dpi: number
  backend: string
  labelFormat: string
}

export interface TextElement {
  id: string
  text: string
  fontName: string
  textSize: number
  hAlign: 'Left' | 'Center' | 'Right'
  vAlign: 'Top' | 'Center' | 'Bottom'
  textOffsetX: number
  textOffsetY: number
  rotateText: number
  blackText: boolean
  outline: boolean
}

export function makeTextElement(fontName = ''): TextElement {
  return {
    id: 'text-' + Math.random().toString(36).slice(2),
    text: '',
    fontName,
    textSize: 36,
    hAlign: 'Center',
    vAlign: 'Center',
    textOffsetX: 0,
    textOffsetY: 0,
    rotateText: 0,
    blackText: true,
    outline: true,
  }
}

export interface AppState {
  // Printers / fonts
  printers: PrinterInfo[]
  fonts: FontInfo[]
  selectedPrinterIndex: number

  // Image source
  sourceImageURL: string | null
  imageSourceKind: ImageSourceKind

  // Image adjustments
  cropImage: boolean
  imgOffsetX: number      // pixels
  imgOffsetY: number      // pixels
  rotateImageAngle: number   // 0 | 90 | 180 | 270

  // Levels / filter
  blackPoint: number      // 0–255
  whitePoint: number      // 0–255
  contrast: number        // 0.3–3.0
  ditherPreview: boolean
  comicFilter: boolean

  // Text overlays
  fontName: string
  textElements: TextElement[]

  // Barcode
  barcodeData: string
  barcodeType: 'QR' | 'Code128' | 'Aztec' | 'DataMatrix'
  barcodeSize: number
  barcodeOffsetX: number
  barcodeOffsetY: number
  barcodeRotate: number
  barcodeHAlign: 'Left' | 'Center' | 'Right'
  barcodeVAlign: 'Top' | 'Center' | 'Bottom'
  barcodeLabel: boolean
  barcodeCanvas: HTMLCanvasElement | null

  // Raw ZPL
  rawZPL: string

  // Cable Label ZPL template
  cableLabelZPLTemplate: string
}

export function defaultState(): AppState {
  return {
    printers: [],
    fonts: [],
    selectedPrinterIndex: 0,

    sourceImageURL: null,
    imageSourceKind: 'none',

    cropImage: false,
    imgOffsetX: 0,
    imgOffsetY: 0,
    rotateImageAngle: 0,

    blackPoint: 5,
    whitePoint: 250,
    contrast: 1.0,
    ditherPreview: true,
    comicFilter: false,

    fontName: '',
    textElements: [makeTextElement()],

    barcodeData: '',
    barcodeType: 'QR',
    barcodeSize: 3,
    barcodeOffsetX: 0,
    barcodeOffsetY: 0,
    barcodeRotate: 0,
    barcodeHAlign: 'Center',
    barcodeVAlign: 'Center',
    barcodeLabel: false,
    barcodeCanvas: null,

    rawZPL: '^XA\n^CFA,30\n^FO50,20\n^FDHello ZPL^FS\n^XZ',
    cableLabelZPLTemplate: '^XA\\n^FO40,400^A0B,50,40^FD$input1$^FS\\n^FO120,400^A0R,50,40^FD$input2$^FS\\n^XZ',
  }
}

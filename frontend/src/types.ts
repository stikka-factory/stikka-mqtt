// Shared TypeScript interfaces for Gostikka

export interface AppInfo {
  name: string
  subtitle: string
  zplExample: string
  zplRawEnabled: boolean
  cableLabelEnabled: boolean
  cableLabelZPLTemplate?: string
}

export interface StaticModeConfig {
  mode: 'mqtt'
  app: AppInfo
  mqtt: MQTTFrontendConfig
  mqttSettingsPassword?: string
}

export interface MQTTFrontendConfig {
  brokerURL: string
  username?: string
  password?: string
  clientIdPrefix?: string
  discoveryWaitMs?: number
}

export interface PrinterStatusMessage {
  printer_name?: string
  name?: string
  online?: boolean
  busy?: boolean
  type?: string
  serial?: string
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
  }
  last_error?: string
}

export interface PrinterInfo {
  index: number
  name: string
  serial: string
  type: string
  dpi: number
  label: {
    width: number         // mm
    length: number        // mm (0 = continuous)
    isRound: boolean
    verticalOffset: number
    cut: boolean
  }
}

export interface FontInfo {
  name: string
  path: string  // URL path like /fonts/SomeFont.ttf
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

export interface ScannedPrinter {
  name: string
  type: string
  connection: string
  serial: string
  dpi: number
  backend: string
  labelFormat: string
}

export interface AppState {
  // Printers / fonts
  printers: PrinterInfo[]
  fonts: FontInfo[]
  selectedPrinterIndex: number

  // Image source
  sourceImageURL: string | null
  imageSourceKind: 'none' | 'cat' | 'dog' | 'dino' | 'upload' | 'webcam'

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

  // Text overlay
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

  // Barcode
  barcodeData: string
  barcodeType: 'QR' | 'Code128' | 'Aztec' | 'DataMatrix'
  barcodeSize: number
  barcodeOffsetX: number
  barcodeOffsetY: number
  barcodeRotate: number
  barcodeHAlign: 'Left' | 'Center' | 'Right'
  barcodeVAlign: 'Top' | 'Center' | 'Bottom'
  barcodeAttachEnd: boolean
  barcodeShowValue: boolean
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

    text: '',
    fontName: '',
    textSize: 36,
    hAlign: 'Center',
    vAlign: 'Center',
    textOffsetX: 0,
    textOffsetY: 0,
    rotateText: 0,
    blackText: true,
    outline: true,

    barcodeData: '',
    barcodeType: 'QR',
    barcodeSize: 3,
    barcodeOffsetX: 0,
    barcodeOffsetY: 0,
    barcodeRotate: 0,
    barcodeHAlign: 'Center',
    barcodeVAlign: 'Center',
    barcodeAttachEnd: false,
    barcodeShowValue: true,
    barcodeCanvas: null,

    rawZPL: '^XA\n^CFA,30\n^FO50,20\n^FDHello ZPL^FS\n^XZ',
    cableLabelZPLTemplate: '^XA\\n^FO40,400^A0B,50,40^FD$input1$^FS\\n^FO120,400^A0R,50,40^FD$input2$^FS\\n^XZ',
  }
}

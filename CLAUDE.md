# Stikka-MQTT — notes for AI assistants

**What it is**: a static web app (GitHub Pages, <https://stikka-factory.github.io/stikka-mqtt/>) for printing labels on printers spread across the network. The browser renders the label itself and publishes the finished print job over MQTT to an ESP32 bridge attached to each printer. There is no server process.

**What it isn't** (anymore): this repo has no Python/FastAPI/NiceGUI backend and no firmware source. The ESP32 firmware lives in the sibling repo [stikka-factory/stikka-esp32](https://github.com/stikka-factory/stikka-esp32); this repo only hosts its prebuilt binaries for the in-browser flasher. Ignore leftovers that still mention a backend or an `esp32/` folder (e.g. Python entries in `.gitignore`, the `/api` proxy in `vite.config.ts`, comments pointing at `esp32/src/...`, parts of `README_DETAILS.md` and `DEVSHELL.md`).

Origin: reimagination of [printit](https://github.com/5shekel/printit).

---

## Architecture

```
Browser                    MQTT broker                  ESP32 bridge        Printer
───────                    ───────────                  ────────────        ───────
Render + encode job  ──→    /<printer>/command/    ──→  stikka-esp32  ──→   ZPL / Brother QL (USB, network)
Subscribe status     ←─     /+/status/# (retained) ←─   status publish

Browser                    Supabase (Postgres + Storage + Realtime)
───────                    ─────────────────────────────────────────
Relay printer status ──→    printers table (upsert; stale after 5 min)
Upload font          ──→    fonts table + `fonts` Storage bucket
Record print         ──→    print_stats row via record_print() RPC (atomic)
Read / subscribe     ←─     all three, live via Realtime
```

- MQTT is the only channel the firmware speaks. Supabase is purely shared storage for browsers.
- All image work happens in the browser (Canvas, dithering, bwip-js barcodes, ZPL/QL/Seiko encoding). The firmware never decodes images; it forwards bytes to the printer.
- Printer list: full status snapshots (messages with a `phase` field) are upserted into Supabase `printers`; every browser reads the list from there. Printers silent for 5 minutes (`NODE_TIMEOUT_MS` in `supabase-client.ts`) drop off. There is no manual "forget".

---

## Repo layout

```
frontend/                     TypeScript + Vite SPA (the whole app)
  src/
    main.ts                   Entry: load config.json, init MQTT/Supabase, build UI
    ui.ts                     All tabs and DOM: Label, Raw ZPL, Cable Label, About, ESP32 Flasher, Fonts
    editor.ts                 Canvas label rendering (image, text elements, barcode, dither, comic)
    mqtt-api.ts               App-level API: printers, fonts, stats, random images, print dispatch by printer type
    mqtt-client.ts            MQTT connection, status subscription, command publishing (PrintCommandPayload)
    supabase-client.ts        Supabase fonts / print_stats / printers read-write-subscribe
    zpl-image.ts              Image → ZPL (^GF, optional Z64 compression), Brother QL raster, Seiko SLP raster
    pdf.ts                    First page of a PDF → image (pdf.js)
    static-config.ts          Loads/normalizes config.json; localStorage for theme + uploader's font cache
    types.ts                  Shared interfaces (StaticModeConfig, PrinterInfo, PrintStats, …) + defaultState()
    layout.css / style.css    Styling
    assets/fonts/             Bundled tribute font (tracked)
  public/
    config.example.json       Template; copy to config.json (gitignored) for local dev
    themes/                   light / dark / haxor CSS
    firmware/                 Flasher artifacts (index.json + per-env bins); rebuilt by CI from stikka-esp32
    fonts/                    Optional extra fonts (gitignored; filled by scripts/get_fonts.sh)
  vite.config.ts              base: '/stikka-mqtt/' (trailing slash required)
supabase/schema.sql           Tables (fonts, print_stats, printers), record_print(), RLS, fonts bucket — run once in the SQL editor
scripts/
  run-stack.sh / stop-stack.sh   Start/stop the Vite dev server (no broker or mock bridge bundled)
  rebuild-all.sh              ../stikka-esp32/scripts/build-firmware.sh, then restart the stack
  get_fonts.sh                Download League of Moveable Type fonts into frontend/public/fonts/
  generate-fonts-index.sh     Write frontend/public/fonts/index.json (runs as predev/prebuild)
.github/workflows/deploy-pages.yml   Build firmware + frontend, write config.json, deploy to Pages
flake.nix / DEVSHELL.md       Nix dev shell (Node 22, PlatformIO, `build-firmware` → ../stikka-esp32)
README.md                     Short user docs; also rendered in the app's About tab (imported by mqtt-api.ts)
README_DETAILS.md             Longer technical docs (partly stale, see above)
CHANGELOG.md
```

---

## Printing: printer type → payload

`printImage()` in `mqtt-api.ts` picks the encoding from the printer's reported `type`:

| Printer `type` | Encoding | `payload_type` / `payload_encoding` |
|---|---|---|
| `zpl`, `zebra` | `imageDataURLToZPL()` | `zpl` / `utf8` |
| `ql`, `brother_ql` | `imageDataURLToQLRasterBase64()` | `ql_raster` / `base64_bytes` |
| `seiko`, `seiko_slp` | `imageDataURLToSeikoRasterBase64()` | `seiko_raster` / `base64_bytes` |
| anything else | raw PNG | `image` / `base64_png` (or `data_url` if not base64) |

Raw ZPL and Cable Label tabs send `zpl` / `utf8` directly. ZPL preview uses the public Labelary API from the browser.

Per-printer knobs (DPI, label size, `zplCompression`, `ql*`, `seiko*`) come from the printer's status message `capabilities` (see `PrinterStatusMessage` in `types.ts`).

Seiko SLP is frontend-only so far: stikka-esp32 has no firmware that accepts `seiko_raster` yet.

### MQTT contract

Publish to `/<printerName>/command/`, one message per job (no chunking):

```json
{
  "job_id": "job-1737...-abc123",
  "sent_at": "2026-07-22T...",
  "printer_name": "my-printer",
  "payload_type": "image|zpl|ql_raster|seiko_raster",
  "payload_encoding": "data_url|utf8|base64_png|base64_bytes|base64_utf8",
  "payload": "..."
}
```

Subscribe to `/+/status/#`. Full snapshots and per-job status updates share the topic; only snapshots carry `phase`. Ground truth: `mqtt-client.ts` here and the firmware in stikka-esp32.

---

## Configuration

`frontend/public/config.json` (shape `StaticModeConfig` in `types.ts`, defaults in `static-config.ts`) is the entire app config. It is gitignored. There is no in-app settings editor.

- **Local dev**: `cp frontend/public/config.example.json frontend/public/config.json`, then set `mqtt.brokerURL` (a WebSocket URL) and `supabase.url` / `supabase.anonKey`.
- **Deploy**: the "Write MQTT config.json" step in `deploy-pages.yml` generates it from repo Variables/Secrets. Changing a deployment means changing those and re-running the workflow.

| Field | Repo var / secret | Default |
|---|---|---|
| `app.name` | var `APP_NAME` | `Stikka-MQTT` |
| `app.subtitle` | var `APP_SUBTITLE` | `Kleben und kleben lassen, IoT-Style` |
| `app.zplExample` | var `APP_ZPL_EXAMPLE` | built-in test label |
| `app.zplRawEnabled` | var `APP_ZPL_RAW_ENABLED` (`true`/`false`) | `true` |
| `app.cableLabelZPLTemplate` | var `APP_CABLE_LABEL_ZPL_TEMPLATE` | built-in two-line template |
| `app.cableLabelEnabled` | var `APP_CABLE_LABEL_ENABLED` (`true`/`false`) | `true` |
| `app.textOverlayEnabled` | var `APP_TEXT_OVERLAY_ENABLED` (`true`/`false`) | `true` |
| `mqtt.brokerURL` | var `MQTT_BROKER_URL` | `ws://localhost:9001` (placeholder) |
| `mqtt.username` | var `MQTT_USERNAME` | empty |
| `mqtt.password` | secret `MQTT_PASSWORD` | empty |
| `mqtt.clientIdPrefix` | var `MQTT_CLIENT_ID_PREFIX` | `stikka-web` |
| `mqtt.discoveryWaitMs` | var `MQTT_DISCOVERY_WAIT_MS` | `1500` |
| `supabase.url` | var `SUPABASE_URL` | none, required |
| `supabase.anonKey` | secret `SUPABASE_ANON_KEY` | none, required |

`initTransport()` throws if `mqtt.brokerURL`, `supabase.url` or `supabase.anonKey` is empty. `config.json` is a public static asset once deployed, so nothing in it is secret; access control is the RLS policies in `supabase/schema.sql` (anon read/write, no password).

Fonts are the one runtime-editable thing: built-ins come from `frontend/public/fonts/` (indexed by `generate-fonts-index.sh`), uploads from the Fonts tab go to Supabase Storage and are visible to everyone.

---

## Development

```bash
nix develop                                   # optional: Node 22, PlatformIO, jq, build-firmware
cp frontend/public/config.example.json frontend/public/config.json   # first time
cd frontend && npm install
npm run dev                                   # http://localhost:5173/stikka-mqtt/
npm run build                                 # tsc + vite build → frontend/dist
```

- No MQTT broker or Supabase is bundled. Bring your own broker (with a WebSocket listener) and a Supabase project with `supabase/schema.sql` applied.
- There are no tests and no linter config; `npm run build` (which runs `tsc`) is the check.
- `./scripts/run-stack.sh` just starts the dev server; test against a real ESP32 bridge on your broker.
- Firmware: clone `stikka-esp32` next to this repo. `build-firmware` (nix) or `../stikka-esp32/scripts/build-firmware.sh` stages bins into `frontend/public/firmware/`.

### Deploy

`deploy-pages.yml` runs on pushes to `main` touching `frontend/**` or the workflow (or manually). It checks out this repo and stikka-esp32 side by side, builds the firmware with PlatformIO into `frontend/public/firmware/`, writes `config.json`, builds the frontend and publishes `frontend/dist` to Pages.

---

## Hardware

- Supported bridge board: ESP32-S3-DevKitC-1 **N16R8** (PSRAM needed to hold a whole job in memory).
- Custom carrier PCB: [stikka-factory/stikka-control](https://github.com/stikka-factory/stikka-control) (KiCad).
- Bridge setup (fallback AP `Stikka-XXXXXX` / `stikkaesp32` at `1.2.3.4`, mDNS `<name>.local`) is documented in `README.md` and stikka-esp32.

## Gotchas

- Vite `base` must keep its trailing slash or `config.json` 404s in production.
- `README.md` is shown inside the app, so write it for end users.
- The URL hash `#<printer-name>` preselects a printer (slugified match), see `ui.ts`.
- `mqtt-dummy` is a frontend fallback printer used when no printers are discovered (`isDummyPrinter()` in `mqtt-api.ts`).

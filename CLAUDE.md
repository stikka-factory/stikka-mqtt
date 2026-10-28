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
| `app.name` | var `APP_NAME` | `Stikka-MQTT` |
| `app.subtitle` | var `APP_SUBTITLE` | `Kleben und kleben lassen, IoT-Style` |
| `app.zplExample` | var `APP_ZPL_EXAMPLE` | built-in ZPL test label |
| `app.zplRawEnabled` | var `APP_ZPL_RAW_ENABLED` (must be exactly `true`/`false`) | `true` |
| `app.cableLabelZPLTemplate` | var `APP_CABLE_LABEL_ZPL_TEMPLATE` | built-in two-line template |
| `app.cableLabelEnabled` | var `APP_CABLE_LABEL_ENABLED` (must be exactly `true`/`false`) | `true` |
| `mqtt.brokerURL` | var `MQTT_BROKER_URL` | `ws://localhost:9001` (placeholder — set this for a working deploy) |
| `mqtt.username` | var `MQTT_USERNAME` | empty |
| `mqtt.password` | secret `MQTT_PASSWORD` | empty |
| `mqtt.clientIdPrefix` | var `MQTT_CLIENT_ID_PREFIX` | `stikka-web` |
| `mqtt.discoveryWaitMs` | var `MQTT_DISCOVERY_WAIT_MS` (must be a bare number) | `1500` |
| `supabase.url` | var `SUPABASE_URL` | empty (required — `initTransport()` throws if unset) |
| `supabase.anonKey` | secret `SUPABASE_ANON_KEY` | empty (required — `initTransport()` throws if unset) |

`config.json` ends up served as a public static asset, so none of this — including the two currently populated from `secrets.*` — is actually confidential once deployed; `secrets.*` here is just about not putting them in the repo/workflow file in plaintext. The two ZPL template vars can hold real multi-line values (GitHub repo Variables support that); the workflow can't default them inline via `${{ vars.X || 'literal' }}` the way the scalar fields do, so their defaults live as bash heredocs in the workflow step instead, applied only when the variable is unset or empty.

There is no in-app editor for any of the above — `app.*`/`mqtt.*`/`supabase.*` are exactly what's in `config.json`, full stop. Changing a deployment's settings means changing repo Variables/Secrets and redeploying. The one exception is fonts, which stay runtime-editable via the Fonts tab and are shared globally through Supabase instead of through `config.json` — see below.

`mode` picks the transport (`initTransport()` in `mqtt-api.ts`):

- `"mqtt"` (GitHub Pages deploy): MQTT broker for jobs/status plus Supabase for fonts/stats/printer list, as described above.
- `"server"`: everything goes through [stikka-server](https://github.com/stikka-factory/stikka-server) (`server-client.ts`): printers, live updates over `/api/ws`, jobs via `POST /api/jobs` addressed by `PrinterInfo.nodeId`, fonts, stats. stikka-server serves the built app at `/` (its Dockerfile builds this repo with `BASE_PATH=/`) and generates `config.json` itself from its `APP_*` env vars, so `mqtt.*`/`supabase.*` are unused. `server.url` overrides the server's base URL (default: same origin). For `npm run dev`, set `"mode": "server"` in your local `config.json`; Vite proxies `/api` and `/uploads` to `STIKKA_SERVER` (default `http://localhost:3000`).

This is the migration away from MQTT/Supabase (step 2 of the plan): both modes work side by side until the firmware speaks the server protocol. The old `"backend"` mode (FastAPI) only exists on `main`.

Fonts uploaded via the in-app Fonts tab are uploaded to a Supabase Storage bucket and recorded in a `fonts` table (`publishFont`/`fetchSupabaseFonts` in `mqtt-api.ts`/`supabase-client.ts`), so a font one browser uploads becomes available to every browser, not just the one that uploaded it — not gated by any password, same trust model as before (RLS policies in `supabase/schema.sql` allow anon read/write). `static-config.ts`'s `localStorage`-backed `loadCustomFonts`/`saveCustomFont` still exist, but only as the uploading browser's own fallback cache (offline/before the Supabase round-trip completes), not the source of truth.

Note: there is no `statusTopicPrefix`/`commandTopicPrefix` config — MQTT topics are hardcoded per-printer in `mqtt-client.ts` (see MQTT Message Contract below), not derived from config.

---

## Dependencies

### Frontend (npm)

- **TypeScript** `^5.3.0` — Type checking
- **Vite** `^5.2.0` — Build tool & dev server
- **bwip-js** `^4.0.0` — Barcode generation (QR, Code 128, etc.)
- **mqtt** `^5.10.4` — MQTT client
- **@supabase/supabase-js** `^2.110.8` — Supabase client (fonts/stats/printer-discovery storage, Realtime, Storage)
- **pdfjs-dist** `^6.1.200` — PDF extraction
- **marked** `^15.0.0` — Markdown rendering

### Backend (Python, via uv) — `main` branch only, not present here

- FastAPI, Uvicorn, pydantic, pyusb, pillow, bwip-js (JS barcode), etc.
- See `pyproject.toml` on `main` for full list

### ESP32 mock bridge (Python, via uv)

- `esp32/tools/mock_bridge_server.py` — run with `uv run python esp32/tools/mock_bridge_server.py ...` (no `pyproject.toml`/`uv.lock` needed for this; `scripts/run-stack.sh` runs `uv sync` first)

### Development

- **Nix** (optional): `nix develop` for hermetic environment (Node 22, Python 3.12 + uv, PlatformIO). No MQTT broker is bundled — bring your own (system package, Docker, remote broker) for local testing.
- **PlatformIO** (for ESP32): `pio` CLI
- **Node.js** ≥ 18

---

## Development Setup

### Using Nix (recommended)

```bash
nix develop
# See DEVSHELL.md for quick commands
```

### Manual Setup

```bash
cd frontend && npm install && cd ..

# Build frontend
cd frontend && npm run build && cd ..
```

There is no Python install step on this branch — `uv sync` / `uv run stikka.py` only apply on `main`.

### Development (Hot-reload)

```bash
cp frontend/public/config.example.json frontend/public/config.json  # first time only
cd frontend && npm run dev   # Vite dev server, http://localhost:5173
```

`frontend/public/config.json` is gitignored — it's local-only, never checked into the repo (production's version is generated at deploy time from repo Variables/Secrets, see Frontend Configuration below). `config.example.json` *is* tracked and is just a starting point to copy from; edit your local `config.json`'s `mqtt.brokerURL` to point at a running MQTT broker (`mode: "mqtt"`) to exercise the print flow. The dev shell no longer bundles a broker (see **Local Test Stack** below) — bring your own (system package, Docker, remote broker).

---

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

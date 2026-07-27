# Stikka-NG Project Documentation

**Project**: Stikka-NG — Web-based label printing app (reimagination of [printit](https://github.com/5shekel/printit))

**Current Focus**: MQTT-based static deployment for ESP32 bridge + browser-side image rendering

**Branch note**: This is the `esp32` branch. Its Python/FastAPI backend was deleted here (commit `b0aa804`, "removed old files") to focus purely on the frontend + MQTT + ESP32 firmware stack — `stikka.py`, `pyproject.toml`, `uv.lock`, etc. do not exist in this checkout. The backend still lives on `main` if you need to cross-reference it.

---

## Project Overview

Stikka-NG is a modular label printing system with:
- **Browser frontend** (TypeScript/Vite): All image processing via Canvas API, barcode generation (bwip-js), font management, plus an in-app ESP32 web flasher
- **ESP32 firmware**: MQTT-based printer bridge (`esp32/`, PlatformIO, work-in-progress)
- **MQTT support**: Static (e.g. GitHub Pages) deployment using WebSocket/MQTT for print jobs, talking directly to the ESP32 bridge — no server required
- **Supabase**: Backs shared/global browser-side state (fonts, print statistics, discovered printer nodes) that used to live as retained MQTT topics — see `supabase-client.ts` and `supabase/schema.sql`. MQTT remains the only channel the ESP32 firmware itself speaks (print jobs, printer status ingestion); Supabase is purely the shared-storage layer browsers read/write
- **Python backend** (FastAPI): exists on `main` only, not in this checkout — REST API, printer communication, config management

### Key Features

- **Multi-printer support (backend mode, `main` branch)**: Debug (file), Brother QL (USB), Seiko SLP (USB), Zebra ZPL (network/MQTT)
- **MQTT print path (this branch)**: Frontend renders the label client-side and publishes the job straight to the ESP32 bridge over MQTT
- **Image sources**: Random animals, file upload (JPEG/PNG/PDF), webcam capture
- **Image adjustments**: Resize, crop, rotate, dither, contrast, comic filter
- **Text overlay**: Word-wrap, font selection, rotation, outline, alignment
- **Barcode generation**: QR, Code 128, Aztec, DataMatrix (via bwip-js)
- **Custom fonts**: Drop `.ttf`/`.otf` into `frontend/public/fonts/` (built-in, part of the deploy) or upload from the in-app Fonts tab at runtime — uploads go to a Supabase Storage bucket + `fonts` table, so they're available to every browser, not just the one that uploaded them (`mqtt-api.ts` → `publishFont`/`fetchFonts`, `supabase-client.ts`). Not password-gated (see Config management below)
- **ESP32 web flasher**: In-browser flashing of firmware built by `scripts/build-firmware.sh` (`ui.ts` → `buildESP32FlasherTab`), served from `frontend/public/firmware/`
- **Raw ZPL editor**: Manual ZPL editing, gated by `app.zplRawEnabled` in config (on in both modes by default). Preview renders via a direct client-side call to the public Labelary API (`mqtt-api.ts` → `previewZPL`) — no backend proxy needed in MQTT mode
- **Cable label generator**: Automated ZPL template for two-line labels, gated by `app.cableLabelEnabled`
- **Print statistics**: Real CSV tracking in backend mode (`main` branch); in MQTT mode counts live in a Supabase `print_stats` row, incremented atomically via the `record_print()` Postgres function (no more client-side read-modify-write race) and shared globally across all browsers via Supabase Realtime, same pattern as shared fonts (`mqtt-api.ts` → `recordPrint`/`fetchStats`/`subscribeSharedStats`, `supabase-client.ts`)
- **Config management**: Password-protected in-app editor in backend mode only (`config_pwd`/`default_config.json`, `main` branch). MQTT mode has no in-app settings editor — `app.*`/`mqtt.*`/`supabase.*` come entirely from `config.json`, written at deploy time by `deploy-pages.yml` from repo Variables/Secrets (see Frontend Configuration below); changing them means changing those and redeploying. The one thing that *is* runtime-editable in MQTT mode is fonts (Fonts tab), which are shared globally via Supabase rather than kept in `config.json` (`mqtt-api.ts`, `supabase-client.ts`)

---

## Architecture

### Data Flow

**Static MQTT Mode (this branch)**:
```
Browser                    MQTT Broker                  ESP32 Bridge        Printer
──────                     ───────────                  ────────────        ───────
Render image      ──→       /<printer>/command/    ──→  Firmware      ──→   ZPL/Network
Subscribe status  ←─        /+/status/# (wildcard) ←─   Status publish (retained)

Browser                    Supabase (Postgres + Storage + Realtime)
──────                     ─────────────────────────────────────────
Relay printer status ──→    printers table (upsert; last_seen cutoff = "forgotten")
Upload font        ──→      fonts table + Storage bucket
Record print        ──→     print_stats row (record_print() RPC, atomic)
Read/subscribe      ←─      all three, live via Realtime
```
Note: topics are printer-scoped (`/<printer>/command/`, `/<printer>/status/`), not prefix-scoped — the `statusTopicPrefix`/`commandTopicPrefix` keys shown in older docs/examples aren't read by the code (`mqtt-client.ts`). MQTT is still the only channel the ESP32 firmware speaks, but the *storage* for fonts/stats/printer-discovery moved to Supabase — see `supabase-client.ts` and `supabase/schema.sql`.

**Backend Mode (`main` branch only — not present in this checkout)**:
```
Browser (TypeScript)              Python Server (FastAPI)        Printers
─────────────────────             ──────────────────────        ────────
Canvas rendering         ──→       /api/print              ──→   Brother QL
Image/font loading       ──→       /api/fonts               ──→   Seiko SLP
Barcode generation       ──→       /api/config             ──→   Zebra ZPL
Preview (dithering)      ──→       /api/printers/scan      ──→   File (debug)
                                   /api/zpl/* (preview)
                                   /api/random/* (images)
                                   /api/fonts/upload
                                   /api/config/upload
```

### Frontend Modules

| File | Purpose |
|---|---|
| `main.ts` | Application entry point, UI initialization |
| `ui.ts` | DOM elements, event listeners, form handling, ESP32 web flasher tab (`buildESP32FlasherTab`) |
| `editor.ts` | Label editor logic, canvas management |
| `mqtt-client.ts` | MQTT connection & subscription handling; relays printer status snapshots into Supabase (`upsertSupabasePrinter`) |
| `mqtt-api.ts` | Print job serialization for MQTT (static mode); orchestrates Supabase-backed fonts/stats/printer-discovery |
| `supabase-client.ts` | Supabase client init + fonts/stats/printers read-write-subscribe (Storage bucket, Postgres tables, Realtime) |
| `types.ts` | TypeScript interfaces for config, printers, jobs |
| `pdf.ts` | PDF page extraction via pdf.js |
| `zpl-image.ts` | ZPL encoding for images; also builds the complete Brother QL raster protocol byte stream client-side for `ql`/`brother_ql` printers (`imageDataURLToQLRasterBase64`) — ported from the firmware's former `ql_raster.cpp`, which decoded/rasterized PNGs on-device before this moved client-side |
| `static-config.ts` | Config loader for GitHub Pages mode |
| `layout.css` / `style.css` | UI styling |

### Backend (Python) — not in this checkout

Removed from the `esp32` branch in commit `b0aa804`. Still present on `main`:

| File (on `main`) | Purpose |
|---|---|
| `stikka.py` | FastAPI server, static file serving, REST endpoints |
| `stikka_print_it.py` | Printer drivers (ZPL, Brother QL, Seiko SLP) |
| `stikka_config.py` | Config loading, label-format parsing, statistics |
| `stikka_label_helper.py` | Logging, random-image fetching, font discovery |

### ESP32 Firmware

`src/` is modularized by concern rather than one file. Env naming is
`<board>_<protocol>_<method>`. `platformio.ini` factors the protocol/method
combinations into shared `env_<protocol>_<method>` base sections (each
setting real `TARGET_NETWORK`/`TARGET_SERIAL`/`TARGET_USB`/`PROTOCOL_QL`
compile switches, not just the `PROTOCOL`/`METHOD` string macros used for
display) that per-board leaf envs `extends` — currently `zpl_network`
(implemented, active), `zpl_serial` (implemented, no board env uncommented
yet), `zpl_usb` (implemented, active), and `ql_usb` (implemented, active —
Brother QL raster protocol, built client-side by the frontend and forwarded
byte-for-byte by this firmware; see limitations in `esp32/README.md`). A new
transport method means a new `src/targets/*_target.cpp` implementing the
shared contract in `targets/target.h`, guarded by its own `TARGET_*` flag; a
new protocol means a new `src/targets/*_protocol.cpp` plus a `PROTOCOL_*`
flag that `mqtt_bridge.cpp` branches on — each combination compiles as its
own firmware, not a runtime option. **Important `extends` gotcha**:
PlatformIO only inherits a key from the parent section if the child doesn't
redefine it — since every section here sets its own `build_flags`, each one
must start with `${<parent>.build_flags}` or the chain silently breaks (a
board env's `TARGET_*`/`PROTOCOL_*` flags just don't reach the compiler,
which surfaces as *link* errors, not compile errors, since the functions
still get declared via the headers).

| File | Purpose |
|---|---|
| `esp32/src/main.cpp` | Entry point — `setup()`/`loop()` orchestration only, wires the modules below together |
| `esp32/src/config.h/.cpp` | `AppConfig` struct, NVS (`Preferences`) load/save, runtime settings dump |
| `esp32/src/logging.h/.cpp` | Ring-buffer logger backing the web Logs tab + serial/UART output (`dbgPrint`/`dbgPrintln`); refuses `debugOutputMode=="usb"` on `TARGET_USB` builds (falls back to `uart`, or disables output if that's also unconfigured) since that build reserves the primary Serial/UART0 for the printer connection |
| `esp32/src/status_led.h/.cpp` | NeoPixel/RGB status LED (green=WiFi+MQTT, yellow=WiFi only, red=none, purple/cyan=MQTT RX/TX) |
| `esp32/src/wifi_manager.h/.cpp` | Station Wi-Fi connect/retry, fallback AP, captive-portal DNS |
| `esp32/src/mqtt_bridge.h/.cpp` | MQTT connect, `/<printer>/command/`+`/<printer>/status/` topics, status publishing, command JSON parsing + chunk reassembly (ZPL `utf8`/`base64_utf8`, image `base64_png`/`data_url`/`base64_chunk`, and `ql_raster` `base64_bytes`/`base64_chunk` — all chunked or single-message), dispatch straight to the compiled-in target. `PROTOCOL_QL` builds only accept `payload_type: "ql_raster"` (pre-rasterized by the frontend, see `zpl-image.ts` below) and reject `"zpl"`/`"image"`; non-QL builds keep accepting `"zpl"`/`"image"` and reject `"ql_raster"`. MQTT receive buffer negotiates up to 65535 bytes (PubSubClient's `bufferSize` is a `uint16_t`) — a hard per-message ceiling independent of the broker's own max packet size; the frontend chunks anything larger |
| `esp32/src/web_ui.h/.cpp` | Config + Logs web UI (`/`, `/save`, `/logs`, `/logs.json`, `/test`); which fields it shows/saves adapts to the compiled-in `TARGET_*`/`PROTOCOL_QL` flags |
| `esp32/src/targets/target.h/.cpp` | Shared target contract (`targetSend`/`targetSendString`/`targetStreamBegin`/`targetStreamWrite`/`targetStreamEnd`/`targetSetup`/`targetMethodName`) plus a write-loop-with-timeout helper shared by the serial/usb targets |
| `esp32/src/targets/network_target.cpp` | `TARGET_NETWORK` ("network" method): relays bytes to a TCP printer host:port (`cfg.zplTargetHost`/`zplTargetPort`) |
| `esp32/src/targets/serial_target.cpp` | `TARGET_SERIAL` ("serial" method): relays bytes to a dedicated hardware UART (UART2, `cfg.printerUartTxPin`/`printerUartRxPin`/`printerUartBaud`) wired straight to the printer |
| `esp32/src/targets/usb_target.cpp` | `TARGET_USB` ("usb" method): relays bytes over the board's own USB/programming port (`Serial`/UART0, `cfg.printerUsbBaud`) |
| `esp32/platformio.ini` | PlatformIO build config — `env_<protocol>_<method>` base sections, one `[env:<board>_<protocol>_<method>]` per active board/combo |
| `esp32/tools/mock_bridge_server.py` | Software bridge simulator for testing without hardware (`uv run python esp32/tools/mock_bridge_server.py ...`) — only exercises the `zpl_network` path (a fake TCP printer), not `serial`/`usb`/`ql` |
| `esp32/README.md` | Firmware setup, source layout, protocol/method matrix, Brother QL raster protocol details, MQTT contract, mock server usage |

**Current device / default build target**: M5Stack Atom (`default_envs = m5stack-atom_zpl_network` in `platformio.ini`)  
**Build**: `pio run` from `esp32/` (builds every active/uncommented env), or `pio run -e m5stack-atom_zpl_network -t upload` to flash a specific one — active envs today: `m5stack-atom_zpl_network`, `m5stack-atom_zpl_usb`, `m5stack-atom_ql_usb`  
**Fallback AP**: if station Wi-Fi is unavailable, firmware opens AP `Stikka-<chip suffix>` / password `stikkaesp32` at `192.168.4.1` for setup

---

## Project Structure

```
stikka-NG/
├── frontend/                    # TypeScript/Vite SPA
│   ├── src/
│   │   ├── main.ts             # Entry point
│   │   ├── ui.ts               # UI components + ESP32 flasher tab
│   │   ├── editor.ts           # Label editor logic
│   │   ├── mqtt-client.ts      # MQTT connection & subscriptions
│   │   ├── mqtt-api.ts         # Print job serialization for MQTT
│   │   ├── supabase-client.ts  # Supabase-backed fonts/stats/printer-discovery storage
│   │   ├── static-config.ts    # Config loader for static/MQTT mode
│   │   ├── types.ts            # TypeScript interfaces
│   │   └── *.ts                # Other utility modules (pdf.ts, zpl-image.ts, ...)
│   ├── public/
│   │   ├── config.json         # Frontend config (mode, MQTT URL) — gitignored, local/per-deploy only
│   │   ├── config.example.json # Tracked template — copy to config.json for local dev
│   │   ├── fonts/              # Custom fonts (.ttf/.otf)
│   │   └── firmware/           # ESP32 build artifacts (generated by build-firmware.sh)
│   ├── package.json            # npm dependencies
│   ├── tsconfig.json           # TypeScript config
│   └── vite.config.ts          # Vite config
├── esp32/                       # ESP32 firmware (PlatformIO)
│   ├── src/main.cpp            # Main firmware
│   ├── platformio.ini          # Build config (board envs)
│   ├── tools/mock_bridge_server.py  # MQTT bridge simulator for testing without hardware
│   └── README.md               # Firmware setup + MQTT contract
├── supabase/
│   └── schema.sql               # Tables (fonts, print_stats, printers), RLS policies, record_print() RPC — run once in the Supabase SQL editor
├── scripts/                     # Helper scripts
│   ├── run-stack.sh            # Start local dev stack (mock bridge + frontend; needs an external MQTT broker)
│   ├── stop-stack.sh           # Stop local dev stack
│   ├── build-firmware.sh       # Build all ESP32 envs, stage web-flasher artifacts
│   ├── rebuild-all.sh          # build-firmware.sh + stop-stack.sh + run-stack.sh
│   └── get_fonts.sh            # Download fonts
├── flake.nix                    # Nix dev environment (adds `build-firmware` command)
├── DEVSHELL.md                  # Nix shell quick reference
├── README.md                    # User-facing documentation (describes backend mode too)
├── CHANGELOG.md                 # Version history
└── CLAUDE.md                    # This file (AI assistant notes)
```

Not present in this checkout (still on `main`): `stikka.py`, `stikka_config.py`, `stikka_print_it.py`, `stikka_label_helper.py`, `pyproject.toml`, `uv.lock`, `default_config.json`, `install.sh`.

---

## Frontend Configuration

Frontend config lives in `frontend/public/config.json` (shape defined by `StaticModeConfig` in `types.ts`). Current file:

```json
{
  "mode": "mqtt",
  "app": {
    "name": "Stikka-NG",
    "subtitle": "MQTT Static Mode",
    "zplExample": "^XA\n^CFA,30\n^FO50,20\n^FDStikka MQTT Test^FS\n^XZ",
    "zplRawEnabled": true,
    "cableLabelEnabled": true
  },
  "mqtt": {
    "brokerURL": "ws://localhost:9001",
    "username": "",
    "password": "",
    "clientIdPrefix": "stikka-web",
    "discoveryWaitMs": 1500
  },
  "supabase": {
    "url": "https://your-project.supabase.co",
    "anonKey": "your-anon-public-key"
  }
}
```

This file doesn't exist in the repo (gitignored, per-deployment/per-machine state) — for a real deploy it's generated at build time by the "Write MQTT config.json" step in `.github/workflows/deploy-pages.yml`, entirely from GitHub repo Variables/Secrets (Settings → Secrets and variables → Actions in the repo on GitHub); for local dev, copy the tracked `frontend/public/config.example.json` (see Development Setup below) and point it at your own broker. Editing a *deployment's* defaults means changing repo Variables/Secrets, not editing code:

| Field | Source | Default if unset |
|---|---|---|
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

Only `mode: "mqtt"` is supported by this checkout's code (`mqtt-api.ts` throws if `config.mode !== 'mqtt'`) — `"backend"` mode requires the FastAPI server, which only exists on `main`.

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

## Build & Run

### Production (static/MQTT mode)

```bash
cd frontend && npm run build && cd ..
# Serve frontend/dist as static files (e.g. GitHub Pages) — no server process needed.
# config.json must point at a reachable MQTT broker/ESP32 bridge.
```

There is no `uv run stikka.py` server process on this branch — that only exists on `main` (backend mode).

### ESP32 Firmware

```bash
cd esp32
pio run                          # Build default env (m5stack-atom_zpl_network)
pio run -e m5stack-atom_zpl_network -t upload  # Flash to device
pio device monitor               # Serial monitor (115200 baud)
```

### Local Test Stack

Use scripts in `scripts/` (see `scripts/run-stack.sh` for details). **No broker is bundled** — export `BROKER_HOST`/`BROKER_PORT` (default `127.0.0.1:1883`) to point at a broker you're already running (system mosquitto, Docker, remote), and make sure `frontend/public/config.json`'s `mqtt.brokerURL` points at that same broker's websocket listener. **No Supabase instance is bundled either** — create a free project at supabase.com, run `supabase/schema.sql` once in its SQL editor, create a public `fonts` Storage bucket if the schema's bucket-creation statements didn't apply on your plan, and set `config.json`'s `supabase.url`/`supabase.anonKey` to that project's values:
- `run-stack.sh` — starts the Python mock ESP32 bridge (`esp32/tools/mock_bridge_server.py`, via `uv run`) pointed at your broker, and the Vite dev server. Note: it runs `uv sync` first (skip with `SKIP_UV_SYNC=1`); there's no `pyproject.toml` at repo root on this branch, so verify that step still works before relying on it.
- `stop-stack.sh` — stops those processes
- `rebuild-all.sh` — `build-firmware.sh` + `stop-stack.sh` + `run-stack.sh`
- `build-firmware.sh` — builds every uncommented `[env:...]` in `esp32/platformio.ini` via `pio`, stages `firmware.bin`/`manifest.json`/`flash.json` under `frontend/public/firmware/<env>/`, and writes `frontend/public/firmware/index.json` for the in-app web flasher (also exposed as the `build-firmware` command inside `nix develop`)

---

## Key Technologies

| Technology | Purpose |
|---|---|
| **TypeScript** | Type-safe frontend development |
| **Vite** | Fast build tool, dev server with HMR |
| **Canvas API** | Real-time image rendering, dithering |
| **FontFace API** | Custom font loading |
| **bwip-js** | Barcode generation (client-side) |
| **MQTT** | Pub/sub for ESP32 bridge mode (`mqtt` npm package, browser WebSocket transport) |
| **pdf.js** | PDF page extraction (`pdf.ts`) |
| **PlatformIO** | ESP32 build & upload |
| **FastAPI / Pydantic** | REST API server (Python) — `main` branch only, not in this checkout |

---

## Important Notes

### Current Focus Areas

1. **MQTT static mode**: Frontend-only deployment via MQTT for printer communication
2. **ESP32 bridge**: Work-in-progress firmware for network ZPL printer bridging
3. **Frontend-driven rendering**: All image processing in browser (no backend image processing)

### Backend Features (`main` branch only — code not present in this checkout)

- FastAPI `/api/*` endpoints for config, fonts, printer discovery
- Brother QL + Seiko SLP USB driver support
- Print statistics CSV logging (in MQTT mode, counts live in Supabase instead — see Key Features above)

### Limitations

- ESP32 firmware's MQTT receive buffer is capped at 65535 bytes (PubSubClient's `bufferSize` field is a `uint16_t`) — this is a hard ceiling regardless of the broker's configured max packet size; jobs above it must be chunked client-side (`esp32/src/main.cpp`, `mqtt-client.ts`)
- `scripts/run-stack.sh` runs `uv sync` in the repo root, but there's no `pyproject.toml` there on this branch — verify this still works, or run with `SKIP_UV_SYNC=1`
- `supabase.url`/`supabase.anonKey` are required, not optional — `initTransport()` throws synchronously if either is missing, same as `mqtt.brokerURL` (no graceful degradation to MQTT-only mode)
- ESP32 firmware still under development

---

## Configuration Reference — backend mode, `main` branch only

The tables below describe the FastAPI backend's own config file (distinct from the frontend's `config.json` — see **Frontend Configuration** above). That backend code doesn't exist in this checkout; kept here for cross-branch reference.

### App Settings (backend `default_config.json`, on `main`)

| Key | Type | Default | Notes |
|---|---|---|---|
| `port` | int | `8000` | HTTP listen port |
| `host` | string | `"0.0.0.0"` | Bind address |
| `ssl` | bool | `false` | Enable HTTPS |
| `name` | string | `"Stikka Factory"` | Browser title |
| `config_pwd` | string | `"stikka"` | Config editor password |
| `fonts_dir` | string | `"fonts"` | Custom fonts directory |
| `use_system_fonts` | bool | `false` | Load OS system fonts |
| `zpl_raw_enabled` | bool | `true` | Show Raw ZPL tab |
| `cable_label_enabled` | bool | `true` | Show Cable Label tab |

### Printer Configuration (backend mode)

Supported printer types: `"file"`, `"brother_ql"`, `"seiko_slp"`, `"zpl"`

Example ZPL printer:
```json
{
  "name": "Zebra ZPL Printer",
  "type": "zpl",
  "backend": "network",
  "connection": "192.168.1.100:9100",
  "dpi": 203,
  "label": {
    "format": "d55",
    "vertical_offset": 4
  }
}
```

---

## MQTT Message Contract (Static Mode)

Defined in `frontend/src/mqtt-client.ts` (`PrintCommandPayload`) and matched by `esp32/src/main.cpp` (`commandTopic()`/`statusTopic()`) — the two agree with each other, and `esp32/README.md`'s contract section now matches (fixed alongside `esp32/tools/mock_bridge_server.py`, which previously subscribed to the old `/command/<printer>` layout and silently never received anything the frontend published).

**Frontend publishes to**: `/<printerName>/command/`

```json
{
  "job_id": "job-1737...-abc123",
  "sent_at": "2026-07-22T...",
  "printer_name": "my-printer",
  "payload_type": "image|zpl|ql_raster",
  "payload_encoding": "data_url|utf8|base64_png|base64_bytes|base64_chunk|utf8_chunk|base64_utf8|base64_utf8_chunk",
  "payload": "data:image/png;base64,...",
  "chunk_index": 0,
  "chunks_total": 1
}
```

Large image/ZPL/ql_raster payloads are split across multiple messages using the `*_chunk` encodings + `chunk_index`/`chunks_total`, but only once the payload exceeds `IMAGE_CHUNK_SIZE`/`ZPL_CHUNK_SIZE`/`QL_RASTER_CHUNK_SIZE` in `mqtt-client.ts` (8000 bytes each — small enough that every individual ESP32-side allocation stays small regardless of total job size, not just under the firmware's 65535-byte MQTT buffer ceiling). ZPL is sent as plain `utf8`/`utf8_chunk` (no base64 wrapping — ZPL is already ASCII-safe JSON text, and base64 would cost 33% for nothing); image and `ql_raster` bytes stay `base64_png`/`base64_bytes`/`base64_chunk` since they're binary. `ql_raster` carries the already-rasterized Brother QL byte stream (built client-side by `zpl-image.ts`, see `esp32/README.md`'s "Brother QL raster protocol" section) — `PROTOCOL_QL` firmware builds only accept this payload_type, not `image`/`zpl`. The firmware forwards whatever it reassembles straight to the target without decoding it (image/zpl on non-QL builds, ql_raster on QL builds).

**Frontend subscribes to**: `/+/status/#` (wildcard across all printers, retained messages included). Full status snapshots (the ones carrying a `phase` field, as opposed to per-job status updates sharing the same topic) are relayed into a Supabase `printers` table (`upsertSupabasePrinter()` in `supabase-client.ts`) rather than kept in a local per-browser map — every browser reads the printer list from there instead, via Supabase Realtime + a 30s poll for age-based staleness. `/_stikka/fonts/` and `/_stikka/stats/` retained topics no longer exist — fonts and print stats moved to Supabase entirely (a `fonts` table + Storage bucket, and a `print_stats` row incremented atomically via `record_print()`), both still not password-gated (see Config management above and `supabase/schema.sql`'s RLS policies).

---

## Files to Read First

1. [README.md](README.md) — User documentation (still describes backend mode in detail; treat as `main`-branch-oriented)
2. [frontend/src/main.ts](frontend/src/main.ts) — Frontend entry point
3. [frontend/src/types.ts](frontend/src/types.ts) — Data model definitions
4. [frontend/src/mqtt-client.ts](frontend/src/mqtt-client.ts) — Ground truth for the MQTT topic/payload contract
5. [frontend/src/supabase-client.ts](frontend/src/supabase-client.ts) — Ground truth for fonts/stats/printer-discovery storage
6. [supabase/schema.sql](supabase/schema.sql) — Tables, RLS policies, `record_print()` RPC
7. [esp32/src/main.cpp](esp32/src/main.cpp) — Ground truth for firmware-side MQTT behavior (more current than `esp32/README.md`)
8. [esp32/README.md](esp32/README.md) — ESP32 setup instructions
9. [DEVSHELL.md](DEVSHELL.md) — Quick Nix shell commands (also references the `main`-branch backend)

---

## Quick Commands

```bash
# Setup
nix develop                          # Enter dev environment
cd frontend && npm install && cd ..  # Frontend deps (no root-level package.json)

# Development
cd frontend && npm run dev           # Frontend dev server (Vite HMR, localhost:5173)
cd esp32 && pio run                  # Build ESP32 firmware (default env: m5stack-atom_zpl_network)

# Building
cd frontend && npm run build         # Build frontend for static/GitHub Pages deploy
cd esp32 && pio run -e m5stack-atom_zpl_network -t upload  # Flash ESP32

# Local MQTT test stack (mock ESP32 bridge + frontend dev server; needs your own broker running)
BROKER_HOST=127.0.0.1 BROKER_PORT=1883 ./scripts/run-stack.sh
./scripts/stop-stack.sh

# Cleanup / full rebuild
./scripts/rebuild-all.sh             # build-firmware.sh + stop-stack.sh + run-stack.sh
```

**Not applicable on this branch**: `uv sync`, `uv run stikka.py` — no Python backend exists here (see `main` branch).
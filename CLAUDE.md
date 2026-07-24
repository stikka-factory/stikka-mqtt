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
- **Python backend** (FastAPI): exists on `main` only, not in this checkout — REST API, printer communication, config management

### Key Features

- **Multi-printer support (backend mode, `main` branch)**: Debug (file), Brother QL (USB), Seiko SLP (USB), Zebra ZPL (network/MQTT)
- **MQTT print path (this branch)**: Frontend renders the label client-side and publishes the job straight to the ESP32 bridge over MQTT
- **Image sources**: Random animals, file upload (JPEG/PNG/PDF), webcam capture
- **Image adjustments**: Resize, crop, rotate, dither, contrast, comic filter
- **Text overlay**: Word-wrap, font selection, rotation, outline, alignment
- **Barcode generation**: QR, Code 128, Aztec, DataMatrix (via bwip-js)
- **Custom fonts**: Drop `.ttf`/`.otf` into `frontend/public/fonts/` (built-in, part of the deploy) or upload from the in-app Fonts tab at runtime — uploads are published retained to the broker (`/_stikka/fonts/`) so they're available to every browser, not just the one that uploaded them (`mqtt-api.ts` → `publishFont`/`fetchFonts`, `mqtt-client.ts`)
- **ESP32 web flasher**: In-browser flashing of firmware built by `scripts/build-firmware.sh` (`ui.ts` → `buildESP32FlasherTab`), served from `frontend/public/firmware/`
- **Raw ZPL editor**: Manual ZPL editing, gated by `app.zplRawEnabled` in config (on in both modes by default). Preview renders via a direct client-side call to the public Labelary API (`mqtt-api.ts` → `previewZPL`) — no backend proxy needed in MQTT mode
- **Cable label generator**: Automated ZPL template for two-line labels, gated by `app.cableLabelEnabled`
- **Print statistics**: Real CSV tracking in backend mode (`main` branch); in MQTT mode `fetchStats()` is a stub that always returns zeros
- **Config management**: Password-protected in-app editor in backend mode only (`config_pwd`/`default_config.json`, `main` branch). MQTT mode has no in-app settings editor — `app.*`/`mqtt.*` come entirely from `config.json`, written at deploy time by `deploy-pages.yml` from repo Variables/Secrets (see Frontend Configuration below); changing them means changing those and redeploying. The one thing that *is* runtime-editable in MQTT mode is fonts (Fonts tab), which are shared globally by publishing retained to the broker (`/_stikka/fonts/`) rather than kept in `config.json` (`mqtt-api.ts`, `mqtt-client.ts`)

---

## Architecture

### Data Flow

**Static MQTT Mode (this branch)**:
```
Browser                    MQTT Broker                  ESP32 Bridge        Printer
──────                     ───────────                  ────────────        ───────
Render image      ──→       /<printer>/command/    ──→  Firmware      ──→   ZPL/Network
Subscribe status  ←─        /+/status/# (wildcard) ←─   Status publish (retained)
```
Note: topics are printer-scoped (`/<printer>/command/`, `/<printer>/status/`), not prefix-scoped — the `statusTopicPrefix`/`commandTopicPrefix` keys shown in older docs/examples aren't read by the code (`mqtt-client.ts`).

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
| `mqtt-client.ts` | MQTT connection & subscription handling |
| `mqtt-api.ts` | Print job serialization for MQTT (static mode) |
| `types.ts` | TypeScript interfaces for config, printers, jobs |
| `pdf.ts` | PDF page extraction via pdf.js |
| `zpl-image.ts` | ZPL encoding for images |
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

| File | Purpose |
|---|---|
| `esp32/src/main.cpp` | Firmware entry point — Wi-Fi/MQTT/printer config web UI, fallback AP mode, subscribes `/<printer>/command/`, publishes `/<printer>/status/`, forwards both ZPL (`utf8`/`base64_utf8`, chunked or single-message) and image (`base64_png`/`data_url`/`base64_chunk`) jobs to a network printer. MQTT receive buffer negotiates up to 65535 bytes (PubSubClient's `bufferSize` is a `uint16_t`) — a hard per-message ceiling independent of the broker's own max packet size; the frontend chunks anything larger |
| `esp32/platformio.ini` | PlatformIO build config — many board `[env:...]` sections defined, most commented out |
| `esp32/tools/mock_bridge_server.py` | Software bridge simulator for testing without hardware (`uv run python esp32/tools/mock_bridge_server.py ...`) |
| `esp32/README.md` | Firmware setup, MQTT contract, mock server usage |

**Current device / default build target**: M5Stack Atom (`default_envs = m5stack-atom` in `platformio.ini`)  
**Build**: `pio run` from `esp32/`, or `pio run -e m5stack-atom -t upload` to flash  
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

`config.json` ends up served as a public static asset, so none of this — including the two currently populated from `secrets.*` — is actually confidential once deployed; `secrets.*` here is just about not putting them in the repo/workflow file in plaintext. The two ZPL template vars can hold real multi-line values (GitHub repo Variables support that); the workflow can't default them inline via `${{ vars.X || 'literal' }}` the way the scalar fields do, so their defaults live as bash heredocs in the workflow step instead, applied only when the variable is unset or empty.

There is no in-app editor for any of the above — `app.*`/`mqtt.*` are exactly what's in `config.json`, full stop. Changing a deployment's settings means changing repo Variables/Secrets and redeploying. The one exception is fonts, which stay runtime-editable via the Fonts tab and are shared globally through the broker instead of through `config.json` — see below.

Only `mode: "mqtt"` is supported by this checkout's code (`mqtt-api.ts` throws if `config.mode !== 'mqtt'`) — `"backend"` mode requires the FastAPI server, which only exists on `main`.

Fonts uploaded via the in-app Fonts tab are published retained to `/_stikka/fonts/` on the broker (`publishFont`/`getRemoteFonts` in `mqtt-api.ts`/`mqtt-client.ts`), so a font one browser uploads becomes available to every browser, not just the one that uploaded it — not gated by any password (see MQTT Message Contract below). `static-config.ts`'s `localStorage`-backed `loadCustomFonts`/`saveCustomFont` still exist, but only as the uploading browser's own fallback cache (offline/before the broker round-trip completes), not the source of truth.

Note: there is no `statusTopicPrefix`/`commandTopicPrefix` config — MQTT topics are hardcoded per-printer in `mqtt-client.ts` (see MQTT Message Contract below), not derived from config.

---

## Dependencies

### Frontend (npm)

- **TypeScript** `^5.3.0` — Type checking
- **Vite** `^5.2.0` — Build tool & dev server
- **bwip-js** `^4.0.0` — Barcode generation (QR, Code 128, etc.)
- **mqtt** `^5.10.4` — MQTT client
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
pio run                          # Build default env (m5stack-atom)
pio run -e m5stack-atom -t upload  # Flash to device
pio device monitor               # Serial monitor (115200 baud)
```

### Local Test Stack

Use scripts in `scripts/` (see `scripts/run-stack.sh` for details). **No broker is bundled** — export `BROKER_HOST`/`BROKER_PORT` (default `127.0.0.1:1883`) to point at a broker you're already running (system mosquitto, Docker, remote), and make sure `frontend/public/config.json`'s `mqtt.brokerURL` points at that same broker's websocket listener:
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
- Print statistics CSV logging (in MQTT mode `fetchStats()` is a stub returning zeros)

### Limitations

- ESP32 firmware's MQTT receive buffer is capped at 65535 bytes (PubSubClient's `bufferSize` field is a `uint16_t`) — this is a hard ceiling regardless of the broker's configured max packet size; jobs above it must be chunked client-side (`esp32/src/main.cpp`, `mqtt-client.ts`)
- `scripts/run-stack.sh` runs `uv sync` in the repo root, but there's no `pyproject.toml` there on this branch — verify this still works, or run with `SKIP_UV_SYNC=1`
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
  "payload_type": "image|zpl",
  "payload_encoding": "data_url|utf8|base64_png|base64_chunk|utf8_chunk|base64_utf8|base64_utf8_chunk",
  "payload": "data:image/png;base64,...",
  "chunk_index": 0,
  "chunks_total": 1
}
```

Large image/ZPL payloads are split across multiple messages using the `*_chunk` encodings + `chunk_index`/`chunks_total`, but only once the payload exceeds `IMAGE_CHUNK_SIZE`/`ZPL_CHUNK_SIZE` in `mqtt-client.ts` (60000 bytes — sized just under the firmware's 65535-byte MQTT buffer ceiling, so most labels go out as one message). ZPL is sent as plain `utf8`/`utf8_chunk` (no base64 wrapping — ZPL is already ASCII-safe JSON text, and base64 would cost 33% for nothing); image bytes stay `base64_png`/`base64_chunk` since they're binary. The firmware forwards whatever it reassembles straight to the network printer without decoding it.

**Frontend subscribes to**: `/+/status/#` (wildcard across all printers, retained messages used for printer discovery) and `/_stikka/fonts/` (retained, single message — JSON array of fonts uploaded via the in-app Fonts tab, shared to every browser; not password-gated, see Config management above)

---

## Files to Read First

1. [README.md](README.md) — User documentation (still describes backend mode in detail; treat as `main`-branch-oriented)
2. [frontend/src/main.ts](frontend/src/main.ts) — Frontend entry point
3. [frontend/src/types.ts](frontend/src/types.ts) — Data model definitions
4. [frontend/src/mqtt-client.ts](frontend/src/mqtt-client.ts) — Ground truth for the MQTT topic/payload contract
5. [esp32/src/main.cpp](esp32/src/main.cpp) — Ground truth for firmware-side MQTT behavior (more current than `esp32/README.md`)
6. [esp32/README.md](esp32/README.md) — ESP32 setup instructions
7. [DEVSHELL.md](DEVSHELL.md) — Quick Nix shell commands (also references the `main`-branch backend)

---

## Quick Commands

```bash
# Setup
nix develop                          # Enter dev environment
cd frontend && npm install && cd ..  # Frontend deps (no root-level package.json)

# Development
cd frontend && npm run dev           # Frontend dev server (Vite HMR, localhost:5173)
cd esp32 && pio run                  # Build ESP32 firmware (default env: m5stack-atom)

# Building
cd frontend && npm run build         # Build frontend for static/GitHub Pages deploy
cd esp32 && pio run -e m5stack-atom -t upload  # Flash ESP32

# Local MQTT test stack (mock ESP32 bridge + frontend dev server; needs your own broker running)
BROKER_HOST=127.0.0.1 BROKER_PORT=1883 ./scripts/run-stack.sh
./scripts/stop-stack.sh

# Cleanup / full rebuild
./scripts/rebuild-all.sh             # build-firmware.sh + stop-stack.sh + run-stack.sh
```

**Not applicable on this branch**: `uv sync`, `uv run stikka.py` — no Python backend exists here (see `main` branch).
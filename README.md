Reimagination of [printit](https://github.com/5shekel/printit), tackling issues that surfaced during 39c3.

Stikka-NG is a web-based label printing app. All image processing runs in the browser — there is no server in the loop. This is the **`esp32` branch**: a static, backend-free deployment (e.g. GitHub Pages) where the browser talks straight to an ESP32 bridge over MQTT, and shared state (fonts, print stats, discovered printers) lives in Supabase instead of a Python backend.

> A Python/FastAPI backend (multi-driver USB/network printing, password-protected config editor, printer scanner) exists on the `main` branch but has been removed here. If you're looking for that, check out `main`.

## Features

- **MQTT print path** — the browser renders the label client-side (Canvas API) and publishes the finished job straight to an ESP32 bridge over MQTT; no server round-trip
- **Image sources** — random cat/dog/dino, file upload (JPEG / PNG / PDF), webcam capture with countdown
- **Text overlay** — word-wrap, alignment, offsets, rotation (−180° to 180° in 15° steps), outline, configurable font
- **Image adjustments** — resize, crop-to-fill / letterbox, offset, rotate (0/90/180/270°), black/white point, contrast, dither, comic filter
- **Barcode overlay** — QR, Code 128, Aztec, DataMatrix (via `bwip-js`); rotation in 90° steps
- **Custom fonts** — drop any `.ttf` / `.otf` into `frontend/public/fonts/` (built into the deploy), or upload from the in-app Fonts tab; uploaded fonts go to Supabase Storage so every browser gets them, not just the uploader
- **Raw ZPL editor** — manual ZPL editing and preview (renders via a direct client-side call to the public Labelary API — no backend proxy needed), gated by `app.zplRawEnabled`
- **Cable label tab** — two-line cable label generator with ZPL template, preview, and direct print, gated by `app.cableLabelEnabled`
- **Print statistics** — tracked in a shared Supabase row, incremented atomically and live-updated across browsers via Supabase Realtime
- **Printer discovery** — printers self-report status over MQTT; the browser relays full status snapshots into a Supabase table so every browser sees the same live printer list
- **ESP32 web flasher** — flash firmware built by `scripts/build-firmware.sh` straight from the browser, no PlatformIO required on the flashing machine
- **Brother QL support** — the frontend builds the complete Brother QL raster byte stream client-side and ships it to a `ql_usb_host`-protocol ESP32 build, which forwards it byte-for-byte over real USB bulk transfers

There is **no in-app settings editor** for MQTT/Supabase/app config in this mode — those come entirely from `config.json`, generated at deploy time from repo Variables/Secrets (see [Frontend configuration](#frontend-configuration)). Printer/network settings (Wi-Fi, MQTT broker, target host) live on the ESP32's own web UI instead of a central config panel.

## Architecture

```
Browser                    MQTT Broker                  ESP32 Bridge        Printer
──────                     ───────────                  ────────────        ───────
Render image      ──→       /<printer>/command/    ──→  Firmware      ──→   ZPL / USB / Brother QL
Subscribe status  ←─        /+/status/# (wildcard) ←─   Status publish (retained)

Browser                    Supabase (Postgres + Storage + Realtime)
──────                     ─────────────────────────────────────────
Relay printer status ──→    printers table (upsert; last_seen cutoff = "forgotten")
Upload font         ──→     fonts table + Storage bucket
Record print         ──→    print_stats row (record_print() RPC, atomic)
Read / subscribe     ←─     all three, live via Realtime
```

The browser does **all** image processing (Canvas rendering, dithering, barcode generation, Brother QL rasterization). The ESP32 firmware never decodes an image — it forwards whatever bytes it's given (ZPL text, PNG, or a pre-rasterized Brother QL command stream) to the printer over whichever transport that firmware build was compiled for (network/serial/USB/USB-host).

## Code structure

| File | Purpose |
|---|---|
| `frontend/src/main.ts` | Application entry point, UI initialization |
| `frontend/src/ui.ts` | DOM elements, event listeners, form handling, ESP32 web flasher tab |
| `frontend/src/editor.ts` | Label editor logic, canvas management |
| `frontend/src/mqtt-client.ts` | MQTT connection & subscription handling; relays printer status into Supabase |
| `frontend/src/mqtt-api.ts` | Print job serialization for MQTT; orchestrates Supabase-backed fonts/stats/printer-discovery |
| `frontend/src/supabase-client.ts` | Supabase client + fonts/stats/printers read-write-subscribe |
| `frontend/src/types.ts` | TypeScript interfaces for config, printers, jobs |
| `frontend/src/pdf.ts` | PDF page extraction via pdf.js |
| `frontend/src/zpl-image.ts` | ZPL image encoding; also builds the complete Brother QL raster byte stream client-side |
| `frontend/src/static-config.ts` | Config loader for static/MQTT mode |
| `esp32/` | ESP32 firmware (PlatformIO) — see `esp32/README.md` |
| `supabase/schema.sql` | Tables (`fonts`, `print_stats`, `printers`), RLS policies, `record_print()` RPC |
| `scripts/` | Dev-stack helpers, firmware build/staging (see below) |

## Installation

### Nix dev shell (recommended)

```sh
nix develop
```

Gives you Node.js, Python 3.12 + uv, and PlatformIO. See `DEVSHELL.md` for quick commands. No MQTT broker or Supabase instance is bundled — bring your own for local testing (see [Local test stack](#local-test-stack) below).

### Manual setup

Prerequisites: Node.js ≥ 18, [uv](https://docs.astral.sh/uv/getting-started/installation/) (only needed for the mock ESP32 bridge script), and PlatformIO (`pio` CLI) if you'll be building firmware.

```sh
git clone <repo-url>
cd stikka-mqtt

cp frontend/public/config.example.json frontend/public/config.json  # first time only
cd frontend && npm install
```

### Development (hot-reload)

```sh
cd frontend && npm run dev   # Vite dev server, http://localhost:5173
```

Edit your local `frontend/public/config.json`'s `mqtt.brokerURL` (and `supabase.url`/`supabase.anonKey`) to point at a running broker/Supabase project to exercise the print flow. `config.json` is gitignored — it's local/per-deployment state, never checked in.

### Production build

```sh
cd frontend && npm run build
# Serve frontend/dist as static files (e.g. GitHub Pages). No server process needed.
```

There's no server process to run — `frontend/dist` is plain static output. See [Deployment](#deployment) below for the GitHub Pages workflow that generates `config.json` automatically.

## Frontend configuration

Config lives in `frontend/public/config.json` (shape: `StaticModeConfig` in `frontend/src/types.ts`), gitignored and per-deployment. Copy `frontend/public/config.example.json` to get started:

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

`mode` must be `"mqtt"` — this checkout doesn't implement backend mode. `supabase.url`/`supabase.anonKey` are required (the app throws on startup if either is empty); `mqtt.brokerURL` needs to point at your broker's **WebSocket** listener, not its raw TCP port. There is no in-app editor for any of this — changing a live deployment means changing the values below and redeploying.

| Field | Purpose | Default if unset |
|---|---|---|
| `app.name` | Browser title / heading | `Stikka-MQTT` |
| `app.subtitle` | Sub-heading text | `Kleben und kleben lassen, IoT-Style` |
| `app.zplExample` | Example ZPL shown in the Raw ZPL tab | built-in test label |
| `app.zplRawEnabled` | Show the Raw ZPL tab | `true` |
| `app.cableLabelZPLTemplate` | ZPL template for cable labels (`$input1$`/`$input2$` substituted) | built-in two-line template |
| `app.cableLabelEnabled` | Show the Cable Label tab | `true` |
| `mqtt.brokerURL` | Broker WebSocket URL, e.g. `wss://broker.example.com:9001` | `ws://localhost:9001` |
| `mqtt.username` / `mqtt.password` | Optional broker credentials | empty |
| `mqtt.clientIdPrefix` | Prefix for the browser's MQTT client ID | `stikka-web` |
| `mqtt.discoveryWaitMs` | How long to wait for retained printer status after connecting | `1500` |
| `supabase.url` | Supabase project URL (required) | — |
| `supabase.anonKey` | Supabase anon/public key (required) | — |

## Supabase setup

Fonts, print statistics, and printer discovery are backed by Supabase (Postgres + Storage + Realtime) instead of retained MQTT topics or a local backend:

1. Create a free project at [supabase.com](https://supabase.com).
2. Run `supabase/schema.sql` once in the project's SQL editor. It creates the `fonts`, `print_stats`, and `printers` tables, the `record_print()` RPC, and RLS policies that allow the anon role to read/write (same trust model as before — none of this is password-gated).
3. If the schema's bucket-creation statements didn't apply on your plan, create a public `fonts` Storage bucket manually.
4. Set `supabase.url` / `supabase.anonKey` in `config.json` to that project's values.

The anon key isn't actually secret once deployed — `config.json` is served as a public static asset either way. Real access control is the RLS policies in `supabase/schema.sql`, not keeping the key hidden.

## MQTT message contract

Defined in `frontend/src/mqtt-client.ts` and matched by `esp32/src/main.cpp` / `esp32/README.md`.

**Frontend publishes to**: `/<printerName>/command/`

```json
{
  "job_id": "job-1737...-abc123",
  "sent_at": "2026-07-22T...",
  "printer_name": "my-printer",
  "payload_type": "image|zpl|ql_raster",
  "payload_encoding": "data_url|utf8|base64_png|base64_bytes|base64_utf8",
  "payload": "data:image/png;base64,..."
}
```

Every job is a single MQTT message — there is no chunking protocol. ZPL is sent as plain `utf8` (already ASCII-safe JSON text); image bytes are `base64_png`/`data_url`; a Brother QL raster job is `ql_raster`/`base64_bytes` (built client-side by `zpl-image.ts`). A `PROTOCOL_QL` firmware build only accepts `ql_raster`; every other build only accepts `zpl`/`image`.

**Frontend subscribes to**: `/+/status/#` (wildcard across all printers, retained messages included). Full status snapshots get relayed into the Supabase `printers` table; `/_stikka/fonts/` and `/_stikka/stats/` retained topics no longer exist (moved to Supabase).

## ESP32 bridge firmware

Firmware lives in `esp32/` (PlatformIO). It connects to Wi-Fi, subscribes to its command topic, and forwards decoded job bytes to whichever transport that build was compiled for — network host:port, a dedicated UART, the board's own USB port, or (for Brother QL) genuine USB host mode.

```sh
cd esp32
pio run                                                  # build the default env
pio run -e esp32-s3-devkitc-1_zpl_network -t upload       # flash a specific env
pio device monitor                                        # serial monitor, 115200 baud
```

**esp32-s3-devkitc-1** (16MB flash + 8MB PSRAM) is the only supported board. Two leaf envs are currently defined: `esp32-s3-devkitc-1_zpl_network` (default) and `esp32-s3-devkitc-1_ql_usb_host`. See **`esp32/README.md`** for the full protocol/method matrix, first-time setup, the Logs tab, mDNS/fallback-AP behavior, and Brother QL raster protocol details.

Firmware can also be flashed from the browser via the in-app **ESP32 flasher tab**, using artifacts staged by `scripts/build-firmware.sh` under `frontend/public/firmware/`.

## Local test stack

No broker or Supabase instance is bundled — bring your own MQTT broker (system package, Docker, remote) and a Supabase project (see above), then:

```sh
BROKER_HOST=127.0.0.1 BROKER_PORT=1883 ./scripts/run-stack.sh
./scripts/stop-stack.sh
```

- `run-stack.sh` — starts the Python mock ESP32 bridge (`esp32/tools/mock_bridge_server.py`, via `uv run`, printer name `stikka-test` by default) pointed at your broker, plus the Vite dev server. It only exercises the `zpl_network` path (a fake TCP printer on `127.0.0.1:9100`), not serial/USB/QL. Runs `uv sync` first — skip with `SKIP_UV_SYNC=1`.
- `stop-stack.sh` — stops those processes
- `build-firmware.sh` — builds every uncommented `[env:...]` in `esp32/platformio.ini`, stages `firmware.bin`/`manifest.json`/`flash.json` under `frontend/public/firmware/<env>/`, and writes `frontend/public/firmware/index.json` for the web flasher (also available as `build-firmware` inside `nix develop`)
- `rebuild-all.sh` — `build-firmware.sh` + `stop-stack.sh` + `run-stack.sh`

Point your local `frontend/public/config.json`'s `mqtt.brokerURL` at your broker's WebSocket listener, matching the printer name used above.

## Deployment

The `esp32` branch is meant to be deployed as static files (e.g. GitHub Pages) with `.github/workflows/deploy-pages.yml`, which:

1. Builds the frontend (`npm ci && npm run build`)
2. Generates `frontend/public/config.json` from repo Variables/Secrets before the build (`Settings → Secrets and variables → Actions` on GitHub) — see the field table above for the mapping (`MQTT_BROKER_URL`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, etc.)
3. Publishes `frontend/dist` to GitHub Pages

Changing a deployment's config means changing those repo Variables/Secrets and re-running the workflow — there's no other place these values live.

## Custom fonts

Drop `.ttf`/`.otf` files into `frontend/public/fonts/` to bundle them with the deploy, or upload from the in-app **Fonts** tab at runtime — uploads go to the Supabase Storage bucket + `fonts` table, so a font one browser uploads is available to every browser. Neither path is password-gated.

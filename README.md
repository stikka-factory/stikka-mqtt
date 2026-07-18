Reimagination of [printit](https://github.com/5shekel/printit), tackling issues that surfaced during 39c3.

Stikka-NG is a web-based label printing app.  
All image processing runs in the browser — the Python server only manages config and talks to printers.

## Features

- **Multi-printer support** — Debug (file download), Brother QL (USB), Seiko SLP (USB), Zebra / ZPL (network)
- **Image sources** — random cat, random dog, file upload (JPEG / PNG / PDF), webcam capture with countdown
- **Text overlay** — word-wrap, alignment, offsets, rotation (−180° to 180° in 15° steps), outline, configurable font
- **Image adjustments** — resize, crop-to-fill / letterbox, offset, rotate (0/90/180/270°), black/white point, contrast, dither, comic filter
- **Barcode overlay** — QR, Code 128, Aztec, DataMatrix; rotation in 90° steps
- **Custom fonts** — drop any `.ttf` / `.otf` into `fonts/`, optionally include system fonts; upload fonts directly from the UI
- **Raw ZPL editor** — manual preview button, preview rendered at the label's aspect ratio; send directly to ZPL printer
- **Cable label tab** — two-line cable label generator with ZPL template, preview, and direct print (can be toggled via `cable_label_enabled`)
- **Print statistics** tracked in a CSV file
- **Password-protected config editor** — load, edit, and save config.json from the browser; upload a config file directly
- **Printer scanner** — auto-discovers Brother QL and Seiko SLP over USB, Zebra printers over the network

## Architecture

```
Browser (TypeScript / Vite)          Python server (FastAPI)
───────────────────────────          ───────────────────────
Image rendering (Canvas API)   →     /api/print   – receives finished PNG, sends to printer
Font loading (FontFace API)    →     /api/fonts   – lists available font files
Barcode generation (bwip-js)   →     /api/printers – returns printer list from config
Preview (Floyd-Steinberg etc.) →     /api/zpl/*   – raw ZPL send / Labelary preview proxy
                                     /api/random/{cat|dog|dino} – image proxy
                                     /api/config  – read/write config.json (password protected)
                                     /api/config/upload – upload a config.json file
                                     /api/fonts/upload  – upload font files (.ttf / .otf)
                                     /api/printers/scan – USB + network printer discovery
```

The server **never processes images** — it only decodes the ready-to-print PNG the browser sends and forwards it to the printer backend.

## Code structure

| File | Purpose |
|---|---|
| `stikka.py` | FastAPI server — REST API, static file serving, printer scan |
| `stikka_print_it.py` | Printer drivers (ZPL, Brother QL, Seiko SLP) |
| `stikka_config.py` | Config loading, label-format parsing, print statistics |
| `stikka_label_helper.py` | Logging setup, random-image fetch, font discovery |
| `frontend/` | Vite + TypeScript SPA (image processing, UI, barcode) |

## Installation

### Nix dev shell

If you use NixOS (or have Nix installed), use the included dev shell:

1. From repo root: `nix develop`
2. See quick commands in `DEVSHELL.md`

### Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Node.js ≥ 18 (for building the frontend)

### Steps

```sh
git clone <repo-url>
cd stikka-NG
cp default_config.json config.json

# Python dependencies
uv sync

# Frontend (build once; server serves from frontend/dist/)
cd frontend && npm install && npm run build && cd ..
```

### Run

```sh
uv run stikka.py
```

Open the URL shown in the logs (default: `http://0.0.0.0:8000`).

### Development (hot-reload frontend)

```sh
# Terminal 1 — Python API server
uv run stikka.py

# Terminal 2 — Vite dev server (proxies /api → port 8000)
cd frontend && npm run dev
```

## Static GitHub Pages + MQTT mode (experimental)

The frontend now supports a static mode for GitHub Pages.
In this mode, browser-side rendering stays the same, but print jobs are sent over MQTT (WebSocket) instead of `/api/print`.

### Current scope

- MVP transport: **ZPL over network via ESP32 bridge**
- MQTT auth: username/password supported
- Printer/admin settings should be managed on the ESP32 web UI
- ESP32 should publish retained status to `/status/<printername>`

### Frontend config

Edit `frontend/public/config.json`:

- `mode`: set to `"mqtt"` for static mode
- `mqtt.brokerURL`: broker websocket URL (for example `ws://broker.local:9001` or `wss://...`)
- `mqtt.username` / `mqtt.password`: optional credentials
- `mqtt.statusTopicPrefix`: default `/status`
- `mqtt.commandTopicPrefix`: default `/command`

### MQTT message contract (current implementation)

- Frontend subscribes to: `/status/+`
- Frontend publishes print commands to: `/command/<printername>`
- Command payload:

```json
{
    "job_id": "job-...",
    "sent_at": "2026-07-18T00:00:00.000Z",
    "printer_name": "my-printer",
    "payload_type": "image|zpl",
    "payload_encoding": "data_url|utf8",
    "payload": "..."
}
```

### Notes

- In static MQTT mode, backend-only tabs/features are hidden (`About`, `Config`, random image fetchers).
- `Raw ZPL` preview is disabled in static mode (no backend Labelary proxy).
- The classic FastAPI mode remains unchanged when `config.json` is absent or `mode` is `"backend"`.

### ESP32 bridge firmware

Initial ESP32 firmware lives in `esp32/`.
Setup and flashing instructions are in `esp32/README.md`.

### Local test stack

A ready-to-run local test environment is available in `local-test/`.
Run instructions: `local-test/README.md`.

## Configuration

The config endpoint is at `/api/config` (or use the in-app config editor).  
Default password: **stikka**.

### App settings

| Key | Description | Default |
|---|---|---|
| `port` | HTTP port | `8000` |
| `host` | Bind address | `"0.0.0.0"` |
| `ssl` | Enable HTTPS (auto-generates self-signed cert) | `false` |
| `ssl_certfile` | Path to TLS certificate | `"certs/cert.pem"` |
| `ssl_keyfile` | Path to TLS key | `"certs/key.pem"` |
| `name` | Browser title and heading | `"Stikka Factory"` |
| `subtitle` | Sub-heading text | `"Kleben und kleben lassen"` |
| `config_pwd` | Password for the config API | `"stikka"` |
| `fonts_dir` | Directory for custom fonts | `"fonts"` |
| `use_system_fonts` | Also load OS fonts | `false` |
| `debug_level` | Log level (`DEBUG`, `INFO`, …) | `"INFO"` |
| `zpl_raw_enabled` | Show the Raw ZPL tab in the UI | `true` |
| `cable_label_enabled` | Show the Cable Label tab in the UI | `true` |
| `cable_label_zpl_template` | ZPL template for cable labels (`$input1$`, `$input2$` are substituted) | see `default_config.json` |
| `colours` | Theme colours (hex) | see `default_config.json` |

### Printer config

The `"printers"` array holds one object per printer.  
A label's dimensions can be given either as separate `width`/`length` keys or as the `format` shorthand.

**`format` shorthand:**

| Pattern | Meaning |
|---|---|
| `"NxM"` | width N mm × length M mm |
| `"Nx0"` | width N mm, continuous (endless) |
| `"dN"` | round label, diameter N mm |

| Key | Description | `"file"` | `"brother_ql"` | `"seiko_slp"` | `"zpl"` |
|---|---|---|---|---|---|
| `"name"` | Display name | any | any | any | any |
| `"serial"` | Serial number (informational) | any | any | any | any |
| `"type"` | Printer driver | `"file"` | `"brother_ql"` | `"seiko_slp"` | `"zpl"` |
| `"backend"` | Transport | `"file"` | `"pyusb"` | `"pyusb"` | `"network"` |
| `"connection"` | Address / path | `"file://debug"` | `usb://VID:PID/serial` | `usb://VID:PID` | `IP:port` |
| `"dpi"` | Dots per inch | `150` | `300` | `300` | `203` |
| `"label.format"` | Dimension shorthand | `"80x80"` | `"62x0"` | `"35x41"` | `"d55"` |
| `"label.vertical_offset"` | Top margin in mm | `0` | `0` | `3` | `4` |
| `"label.cut"` | Feed/cut after print | `true` | `true` | `false` | `false` |

#### Example

```json
"printers": [
    {
        "name": "Debug Printer",
        "serial": "debug",
        "connection": "file://debug",
        "type": "file",
        "backend": "file",
        "dpi": 150,
        "label": { "format": "80x80", "cut": true, "vertical_offset": 0 }
    },
    {
        "name": "Brother QL-720NW",
        "serial": "000J6Z777993",
        "connection": "usb://0x04f9:0x2044/000J6Z777993",
        "type": "brother_ql",
        "backend": "pyusb",
        "dpi": 300,
        "label": { "format": "62x0", "cut": true, "vertical_offset": 0 }
    },
    {
        "name": "Seiko SLP-650",
        "serial": "32115260B0",
        "connection": "usb://0x0619:0x0126",
        "type": "seiko_slp",
        "backend": "pyusb",
        "dpi": 300,
        "label": { "format": "35x41", "cut": false, "vertical_offset": 3 }
    },
    {
        "name": "Zebra ZD410",
        "serial": "50J195204102",
        "type": "zpl",
        "connection": "192.168.0.142:9100",
        "backend": "network",
        "dpi": 203,
        "label": { "format": "d55", "cut": false, "vertical_offset": 0 }
    }
]
```

## Printer scanner

The scanner is accessible from the config panel (password required).  
It discovers:

| Printer type | Method |
|---|---|
| Brother QL | `/sys/bus/usb/devices` matched by VID `0x04F9` + PID. Queries the printer's USB status command to read the currently loaded label size. |
| Seiko SLP | `/sys/bus/usb/devices` matched by VID `0x0619` + PID. Returns the default label format for the model. |
| Zebra / ZPL | Scans all local /24 subnets. A host is included when port 9100 is open and either its ARP MAC matches a known Zebra OUI or port 80 is also open. Hostname is resolved via reverse DNS or HTTP page title. |

Scanned printers are returned as JSON and can be added directly to the config.

## USB permissions (Linux)

USB printers need a udev rule so the app can access them without running as root.

```sh
sudo cp 90-brother_ql.rules /etc/udev/rules.d/
sudo cp 90-seiko_slp.rules  /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Then unplug and replug the printer.

## Running as a systemd service

Edit `stikka-NG.service` — replace `<USER>` with your username and verify the `uv` path (`which uv`).

```ini
[Unit]
Description=Stikka-NG label printer
After=network.target

[Service]
ExecStart=/home/<USER>/.local/bin/uv run stikka.py
WorkingDirectory=/home/<USER>/stikka-NG
Restart=always
User=<USER>
Group=<USER>

[Install]
WantedBy=multi-user.target
```

```sh
sudo systemctl daemon-reload
sudo systemctl enable stikka-NG.service
sudo systemctl start stikka-NG.service
sudo journalctl -u stikka-NG.service --follow
```

## Custom fonts

Drop any `.ttf` or `.otf` files into the `fonts/` directory, or upload them directly from the **Config** tab in the UI (password required — fonts are saved to `fonts_dir` and the font list is refreshed automatically).  
The server lists them at `/api/fonts`; the browser loads them on demand via the FontFace API.

## Disable sleep on Brother QL

```sh
# Find the printer identifier
uv run python -c "from brother_ql.backends.helpers import discover; print(discover('pyusb'))"

# Disable power-off (replace identifier as needed)
brother_ql -p usb://0x04f9:0x2044/000J6Z777993 configure set power-off-delay 0
```


Reimagination of [printit](https://github.com/5shekel/printit), tackling issues that surfaced during 39c3.

Stikka-NG is a web-based label printing app.  
All image processing runs in the browser — the Python server only manages config and talks to printers.

## Features

- **Multi-printer support** — Debug (file download), Brother QL (USB), Seiko SLP (USB), Zebra / ZPL (network)
- **Image sources** — random cat, random dog, file upload (JPEG / PNG / PDF), webcam capture with countdown
- **Text overlay** — word-wrap, alignment, offsets, rotation, outline, configurable font
- **Image adjustments** — resize, crop-to-fill / letterbox, offset, rotate, black/white point, contrast, dither, comic filter
- **Barcode overlay** — QR, Code 128, Aztec, DataMatrix
- **Custom fonts** — drop any `.ttf` / `.otf` into `fonts/`, optionally include system fonts
- **Raw ZPL editor** with live preview via the [Labelary API](https://labelary.com/)
- **Print statistics** tracked in a CSV file
- **Password-protected config editor**
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

Drop any `.ttf` or `.otf` files into the `fonts/` directory.  
The server lists them at `/api/fonts`; the browser loads them on demand via the FontFace API.

## Disable sleep on Brother QL

```sh
# Find the printer identifier
uv run python -c "from brother_ql.backends.helpers import discover; print(discover('pyusb'))"

# Disable power-off (replace identifier as needed)
brother_ql -p usb://0x04f9:0x2044/000J6Z777993 configure set power-off-delay 0
```

## Features

- **Multi-printer support** — Debug (file download), Brother QL (USB), Seiko SLP (USB), Zebra / ZPL (network)
- **Image sources** — random cat, random dog, file upload (JPEG / PNG / PDF), webcam capture with countdown
- **Text overlay** — word-wrap, alignment, offsets, rotation, outline, configurable font
- **Image adjustments** — resize, crop-to-fill / letterbox, offset, rotate, black/white point, contrast, dither preview
- **Custom fonts** — drop any `.ttf` / `.otf` into `fonts/`, optionally include system fonts
- **Raw ZPL editor** with live preview via the [Labelary API](https://labelary.com/)
- **Print statistics** tracked in a CSV file
- **Password-protected config editor** at `/config`

## Code structure

| File | Purpose |
|---|---|
| `stikka.py` | App entry point |
| `stikka_webui.py` | NiceGUI page definitions, config & stats management |
| `stikka_webui_handler.py` | UI event callbacks (`HomepageHandlers` class) |
| `stikka_label_helper.py` | Image/label creation, font discovery, render pipeline |
| `stikka_print_it.py` | Printer drivers (ZPL, Brother QL, Seiko SLP) |

## Installation

### Prerequisites

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) if you haven't already.

### Steps

```sh
git clone <repo-url>
cd stikka-NG
cp default_config.json config.json
uv sync
```

### Test run

```sh
uv run stikka.py
```

Open the URL shown in the logs (default: `http://0.0.0.0:8000`).

## Configuration

Navigate to `http://hostname:port/config` and log in with the default password **stikka**.

### App settings

| Key | Description | Default |
|---|---|---|
| `port` | HTTP port | `8000` |
| `host` | Bind address | `"0.0.0.0"` |
| `name` | Browser title and heading | `"Stikka Factory"` |
| `subtitle` | Sub-heading text | `"Kleben und kleben lassen"` |
| `config_pwd` | Password for `/config` | `"stikka"` |
| `fonts_dir` | Directory for custom fonts | `"fonts"` |
| `use_system_fonts` | Also load OS fonts | `false` |
| `debug_level` | Log level (`DEBUG`, `INFO`, …) | `"DEBUG"` |
| `dark_mode` | Enable dark UI theme | `true` |
| `raw_zpl_enabled` | Show the Raw ZPL tab | `true` |
| `colours` | NiceGUI theme colours (hex) | see below |

#### Default `config.json`

```json
{
    "port": 8000,
    "host": "0.0.0.0",
    "fonts_dir": "fonts",
    "use_system_fonts": false,
    "config_pwd": "stikka",
    "name": "Stikka Factory",
    "subtitle": "Kleben und kleben lassen",
    "debug_level": "DEBUG",
    "raw_zpl_enabled": true,
    "dark_mode": true,
    "colours": {
        "primary": "#55e84a",
        "secondary": "#08940a",
        "brand": "#cf7efb",
        "accent": "#B0C4DE",
        "dark_pages": "#fc12ba",
        "positive": "#32CD32",
        "negative": "#FF4500",
        "info": "#1E90FF",
        "warning": "#FFD700"
    },
    "printers": [ ... ]
}
```

### Printer config

The `"printers"` array holds one object per printer.

| Key | Description | `"file"` | `"brother_ql"` | `"seiko_slp"` | `"zpl"` |
|---|---|---|---|---|---|
| `"name"` | Display name in the UI | any | any | any | any |
| `"serial"` | Printer serial (informational only) | any | any | any | any |
| `"type"` | Printer driver | `"file"` | `"brother_ql"` | `"seiko_slp"` | `"zpl"` |
| `"backend"` | Transport | `"file"` | `"pyusb"` | `"pyusb"` | `"network"` |
| `"connection"` | Address / path | `"file://debug"` | `usb://VID:PID/serial` ¹ | `usb://VID:PID` ² | `IP:port` ³ |
| `"dpi"` | Dots per inch | `150` | `300` | `300` | `203` |
| `"label.width"` | Label width in mm | | | `35` | |
| `"label.length"` | Label height in mm (0 = continuous) | | `0` | `46` | |
| `"label.vertical_offset"` | Top margin in mm | | | | `3.5` |
| `"label.cut"` | Feed/cut after print | | `true` | | |

¹ Run `uv run brother_ql discover` — output looks like `usb://0x04f9:0x2044/000J6Z777993`  
² Format is `usb://0xVVVV:0xPPPP` — find VID/PID in `lsusb` or the udev rules file  
³ Find the printer's IP; raw printing port is usually `9100`

#### Full example

```json
"printers": [
    {
        "name": "Debug Printer",
        "serial": "000J6Z777993",
        "connection": "file://debug",
        "type": "file",
        "backend": "file",
        "dpi": 150,
        "label": { "cut": true, "width": 80, "length": 80, "vertical_offset": 0 }
    },
    {
        "name": "Brother QL-720NW",
        "serial": "000J6Z777993",
        "connection": "usb://0x04f9:0x2044/000J6Z777993",
        "type": "brother_ql",
        "backend": "pyusb",
        "dpi": 300,
        "label": { "cut": true, "width": 50, "length": 0, "vertical_offset": 0 }
    },
    {
        "name": "Seiko SLP-650",
        "serial": "32115260B0",
        "connection": "usb://0x0619:0x0126",
        "type": "seiko_slp",
        "backend": "pyusb",
        "dpi": 300,
        "label": { "cut": false, "width": 35, "length": 46, "vertical_offset": 0 }
    },
    {
        "name": "Zebra ZD410",
        "serial": "50J195204102",
        "type": "zpl",
        "connection": "192.168.0.142:9100",
        "backend": "network",
        "dpi": 203,
        "label": { "cut": false, "width": 55, "length": 67, "vertical_offset": 3.5 }
    }
]
```

## USB permissions (Linux)

USB printers need a udev rule so the app can access them without running as root.  
Copy the provided rules files to `/etc/udev/rules.d/` and reload:

```sh
# Brother QL
sudo cp 90-brother_ql.rules /etc/udev/rules.d/

# Seiko SLP
sudo cp 90-seiko_slp.rules /etc/udev/rules.d/

sudo udevadm control --reload-rules && sudo udevadm trigger
```

Then unplug and replug the printer.

## Running as a systemd service

Copy `stikka-NG.service` to `/etc/systemd/system/`, replace `<USER>` with your username (default on a Pi: `pi`), and verify the `uv` path with `which uv`.

```ini
[Unit]
Description=sticker factory
After=network.target

[Service]
ExecStart=/bin/bash -c '/home/<USER>/.local/bin/uv run stikka.py'
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
```

Follow logs:

```sh
sudo journalctl -u stikka-NG.service --follow
```

## Custom fonts

Drop any `.ttf` or `.otf` files into the `fonts/` directory (or use the helper scripts in `fonts/`).  
The app picks them up automatically on next start.  
A preview sheet is generated at `docs/fonts_preview.jpg`.

## Disable sleep on Brother QL

To stop the printer entering sleep mode, use `brother_ql` from within the project venv.

```sh
# Find the printer ID
brother_ql discover
# → Found compatible printer QL-720NW at: usb://0x04f9:0x2044/000J6Z777993

# Disable power-off
brother_ql -p usb://0x04f9:0x2044/000J6Z777993 configure set power-off-delay 0

# Verify
brother_ql -p usb://0x04f9:0x2044/000J6Z777993 configure get power-off-delay
```
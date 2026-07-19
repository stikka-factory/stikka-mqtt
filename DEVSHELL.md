# Nix Dev Shell Quickstart

This repository includes a flake-based dev shell.

## Enter shell

From the repository root:

nix develop

## What is included

- Node.js + npm for frontend build and dev server
- Python 3.12 + uv for backend dependencies and run
- mosquitto clients for MQTT testing

## Common commands

Backend:

uv sync
uv run stikka.py

Frontend:

cd frontend
npm install
npm run dev
npm run build

MQTT quick test:

mosquitto_sub -h <broker-host> -p 1883 -t '/status/+'
mosquitto_pub -h <broker-host> -p 1883 -t '/command/<printername>' -m '{"job_id":"demo","printer_name":"<printername>","payload_type":"zpl","payload_encoding":"utf8","payload":"^XA^FO40,40^FDHello^FS^XZ"}'

## ESP32 development

Use the VS Code PlatformIO plugin and open the esp32 folder in this repo:

- Project folder: esp32
- Build target: esp32dev
- Upload target: your connected board

## Build all ESP32 firmware artifacts for flasher hosting

Inside `nix develop`, run:

build-firmware

This command:

- builds every `[env:<name>]` from `esp32/platformio.ini`
- copies firmware outputs into `frontend/public/firmware/<env>/`
- writes `frontend/public/firmware/index.json`

The `frontend/public/firmware` folder can be served by Vite/static hosting and consumed by the frontend flasher tab.

# Local Test Environment

This starts a full local MQTT test stack for the static frontend mode:

- Mosquitto broker
  - MQTT TCP: 127.0.0.1:1883
  - MQTT WebSocket: 127.0.0.1:9001
- Mock ESP bridge (`esp32/tools/mock_bridge_server.py`)
- Frontend Vite dev server

## One command

From repo root:

nix develop path:. -c ./local-test/run-stack.sh

Then open:

http://127.0.0.1:5173/stikka-NG/

## Environment overrides

- `PRINTER_NAME` (default: `stikka-test`)
- `FRONTEND_HOST` (default: `127.0.0.1`)
- `FRONTEND_PORT` (default: `5173`)
- `SKIP_UV_SYNC=1` to skip dependency sync on repeat runs

Example:

PRINTER_NAME=label-a SKIP_UV_SYNC=1 nix develop path:. -c ./local-test/run-stack.sh

## Frontend MQTT config

Ensure `frontend/public/config.json` uses:

- `"mode": "mqtt"`
- `"mqtt.brokerURL": "ws://localhost:9001"`
- `"mqtt.commandTopicPrefix": "/command"`
- `"mqtt.statusTopicPrefix": "/status"`

The printer list appears automatically when the frontend receives retained status from `/status/<printername>`.

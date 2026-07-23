# ESP32 MQTT ZPL Bridge (MVP)

This folder contains the first firmware implementation for the ESP32 bridge.

Current scope:

- Configure Wi-Fi, MQTT and printer settings via web UI
- Subscribe to /<printername>/command/
- Publish status to /<printername>/status/ (retained)
- Accept ZPL jobs (utf8/base64_utf8, chunked or single-message) and raw/base64
  image jobs, forwarding to a network printer target host:port
- Fallback AP mode if Wi-Fi is missing or unavailable

Current limitation:

- The MQTT client (PubSubClient) negotiates a receive buffer up to 65535
  bytes at connect time; that's a hard per-message ceiling regardless of the
  broker's own max packet size. Jobs are chunked client-side above that.

## Fallback AP mode

If station Wi-Fi is not configured or cannot connect for about 20 seconds,
the bridge opens an AP so you can still configure it.

- SSID: Stikka-<chip suffix>
- Password: stikkaesp32
- AP IP: 192.168.4.1

The AP state is shown on the setup page.

## Build and flash with PlatformIO

1. Open this folder in VS Code with PlatformIO plugin:

esp32

2. Select environment:

env:esp32dev

Available environments now include:

- env:esp32dev
- env:esp32doit-devkit-v1
- env:nodemcu-32s
- env:wemos_d1_mini32
- env:lolin32
- env:lolin_d32
- env:featheresp32
- env:tinypico
- env:m5stack-core-esp32
- env:m5stack-fire
- env:m5stack-atom
- env:heltec_wifi_kit_32
- env:esp32-s2-saola-1
- env:esp32-c3-devkitm-1
- env:esp32-s3-devkitc-1

Example CLI usage:

pio run -e m5stack-atom -t upload

To build all configured board environments and stage web-flasher artifacts, use the repo dev-shell command:

build-firmware

Output location:

- frontend/public/firmware/index.json
- frontend/public/firmware/<env>/firmware.bin (and bootloader/partitions when available)

3. Build and upload from PlatformIO UI.

4. Open serial monitor at 115200 baud.

## First-time setup

1. Power the board and open its IP in browser (from your router DHCP list).
2. Fill in:
- Wi-Fi SSID and password
- MQTT broker host/port and credentials
- Printer name
- ZPL target host and port
- "Printer supports compressed graphics (:Z64:/:B64:)" -- leave this off unless you've
  confirmed image labels print correctly with it on. Not every ZPL-compatible printer
  implements this optional encoding; when unsupported it's a silent aborted download
  (nothing prints, no error on the wire). When on, image jobs are sent zlib-compressed
  (`:Z64:`), which is usually enough to avoid MQTT chunking entirely.
3. Click Save and reconnect.
4. Click Send test ZPL.

## MQTT contract used by firmware

Subscribe:

/<printername>/command/

Publish retained status:

/<printername>/status/

Command payload example (single message, under the ~65535-byte buffer ceiling):

{
  "job_id": "job-123",
  "printer_name": "my-printer",
  "payload_type": "zpl",
  "payload_encoding": "utf8",
  "payload": "^XA^FO40,40^FDHello^FS^XZ"
}

Larger jobs are split client-side into multiple messages sharing one job_id,
using payload_encoding utf8_chunk/base64_utf8_chunk (zpl) or base64_chunk
(image), plus chunk_index/chunks_total fields:

{
  "job_id": "job-123",
  "printer_name": "my-printer",
  "payload_type": "zpl",
  "payload_encoding": "utf8_chunk",
  "payload": "...",
  "chunk_index": 0,
  "chunks_total": 3
}

Job status payload example:

{
  "printer_name": "my-printer",
  "job_id": "job-123",
  "status": "accepted|done|failed",
  "message": "..."
}

## Local mock test server (without ESP hardware)

There is a software bridge simulator at:

esp32/tools/mock_bridge_server.py

Run it with uv:

uv sync
uv run python esp32/tools/mock_bridge_server.py --broker-host 127.0.0.1 --broker-port 1883 --printer-name stikka-test

This mock server:

- publishes retained printer status to /stikka-test/status/
- subscribes to /stikka-test/command/
- accepts ZPL and image commands, including chunked jobs
- starts a local fake TCP printer on 127.0.0.1:9100 and prints received ZPL to console

Point frontend static config to the same broker and printer name to test end-to-end.

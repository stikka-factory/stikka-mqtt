## Adding a printer

There's no "add printer" button in this app — each ESP32 bridge configures itself and announces its presence over MQTT once it's set up. Once it publishes status, it shows up here automatically.

1. **Flash the bridge firmware** onto the ESP32 (use the ESP32 Flasher tab in this app, or `pio run -e esp32-s3-devkitc-1 -t upload` from the `stikka-esp32` firmware repo).
2. **Power the board.** If it has no saved Wi-Fi, it opens a fallback access point named `Stikka-<chip suffix>` (password `stikkaesp32`). Connect to that network and browse to `1.2.3.4`.
3. **Step 1 of setup:** Wi-Fi SSID/password, MQTT broker host/port (plus TLS and credentials if your broker needs them), printer brand (Zebra/generic ZPL or Brother QL), and connection method (network/serial/USB). Click **Save and continue** — the device reconnects using the new Wi-Fi.
4. **Step 2 of setup** (appears once you reconnect to the device on your normal network): printer name — this becomes the MQTT topic (`/<printer name>/status/`, `/<printer name>/command/`), so it must be unique per bridge — plus location (optional), DPI, label width/length (0 = endless label), and whichever fields your chosen brand/method need (e.g. target host/port for network). Click **Save and reconnect**.
5. Back in this app, the printer appears in the printer list within a few seconds — no registration step here, it's picked up straight from the broker via Supabase.

## Removing a printer

There's no manual "forget" step either — a printer drops off the list on its own once it stops publishing status for 5 minutes straight (powered off, disconnected, etc).

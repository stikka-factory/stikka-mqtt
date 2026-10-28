## Overview 

Webservice to remotely print on label printers spread all over the galaxy with the power of IoT and AI (buzzwords for investors)


## How to print stuff

1. Open [stikka-factory.github.io/stikka-mqtt](https://stikka-factory.github.io/stikka-mqtt/).
2. Pick your printer from the dropdown at the top of the **Label** tab. Only printers that are online and have reported their status in the last 5 minutes show up.
   - Tip: `https://stikka-factory.github.io/stikka-mqtt/#<printer-name>` preselects a printer (e.g. `#test-brother`), handy for a QR code stuck on the printer itself.
3. Build your label:
   - **Image**: click or drop an image / PDF onto the upload area, grab a random cat or dog, or snap one with the webcam. Crop, rotate, offset, contrast, black/white point, comic filter and dither are under *Image Options*.
   - **Text**: add one or more text elements under *Text Overlay* (font, size, alignment, rotation, outline).
   - **Barcode**: generate a QR, Code 128, Aztec or DataMatrix code under *Barcode*.
4. Check the preview. It's rendered for the selected printer's label size and DPI, so pick the printer first.
5. Hit **Print Stikka**. *Download* saves the rendered label instead, if you just want the file.

Other tabs:

- **Raw ZPL**: paste or write ZPL by hand and send it straight to a Zebra printer (preview via Labelary).
- **Cable Label**: two-line cable label from a ZPL template, for Zebra printers.
- **Fonts**: upload a `.ttf` / `.otf`; it's shared with everyone using the site.
- **ESP32 Flasher**: flash the bridge firmware onto a new board (see [Printer setup](#printer-setup)).
- **About**: connection state, print statistics and this README.

## Architecture

* One central Webapp for printing with a db for settings, seen printers and fonts.
* Each printer has an ESP32 connected to it.
* Communication between the printers and Webapp is done over MQTT.
   1. Each printer publishes its status on `/pintername/status/` with the settings done in the ESP32 Firmware.
   2. When a printer is announced and online it's shown in the dropdown.
   3. Printjobs are sent to `/pintername/command/` which the printer is subscribed to.

### Supported boards

- ESP32-S3 DevKitC-1 N16R8 ([AliExpress example](https://www.aliexpress.com/item/1005012092039320.html)) be sure to get the N16R8 version (Enough RAM for images needed)

### Supported printers

| Printer | Method | Description |
|---|---|---|
| Zebra / ZPL | Network | Printer connected to the same network as the ESP32 (not recommended) |
| Zebra / ZPL | USB | Printer connected to the USB-B port of the printer |
| Brother QL | USB | Printer connected to the USB-B port of the printer |
| Seiko SLP | USB | Printer connected to the USB-B port of the printer |


### ESP32 Firmware

Bridge firmware source: [github.com/stikka-factory/stikka-esp32](https://github.com/stikka-factory/stikka-esp32) — WebUI-configurable firmware for the ESP32-S3 N16R8 module that connects it to Stikka-MQTT.


## Printer setup

### Add a new printer

1. On the ESP32 board there are 2 open solder jumper, they need to be bridged.
2. Connect to USB port mamed **COM** for flashing.
3. Flash the ESP using the ESP32 Flasher tab on [stikka-factory.github.io/stikka-mqtt](https://stikka-factory.github.io/stikka-mqtt/).
4. If the ESP32 isn't connected to a known network, it makes its own named `Stikka-XXXXXX`.
5. Connect to it using password `stikkaesp32`.
6. The WebUI is on IP `1.2.3.4`. It should lead you through the setup process.
   - MQTT settings for [stikka-factory.github.io/stikka-mqtt](https://stikka-factory.github.io/stikka-mqtt/) are already set up.
   - After setting the WLAN or changing the printer typ the ESP32 restarts.
7. Don't forget to give it a name, the default name is ignored.
8. The ESP32 webUI should be reachable under `<name>.local` (slugified: **Test_Brother** becomes `test-brother.local`)

### Updating the printer

Updating can be done using the Firmware tab on the ESP32 WebUI (download firmware.bin from the ESP32 Flasher tab) or using the ESP32 Flasher.

### Removing a printer

There's no manual "forget" step either — a printer drops off the list on its own once it stops publishing status for 5 minutes straight (powered off, disconnected, etc).




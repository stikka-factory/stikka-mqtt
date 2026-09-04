## Overview 

Webservice to remotely print on label printers spread all over the galaxy with the power of IoT and AI (buzzwords for investors)


## How to print stuff

COMMING SOON

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
| Seiko SPL | USB | Printer connected to the USB-B port of the printer |


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




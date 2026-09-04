## Overview 

Webservice to remotely print on label printers spread all over the galaxy with the power of IoT and AI (buzzwords for investors)

## ESP32 Firmware

Bridge firmware source: [github.com/stikka-factory/stikka-esp32](https://github.com/stikka-factory/stikka-esp32) — WebUI-configurable firmware for the ESP32-S3 N16R8 module that connects it to Stikka-MQTT.

### Supported boards

- ESP32-S3 DevKitC-1 N16R8 ([AliExpress listing](https://www.aliexpress.com/item/1005012092039320.html))

### Supported printers

| Printer | Method | Description |
|---|---|---|
| Zebra / ZPL | Network | Printer connected to the same network as the ESP32 (not recommended) |
| Zebra / ZPL | USB | Printer connected to the USB-B port of the printer |
| Brother QL | USB | Printer connected to the USB-B port of the printer |
| Seiko SPL | USB | Printer connected to the USB-B port of the printer |

## Setup

### Add a new printer

1. On the ESP32 board there are 2 open solder jumper, they need to be bridged.
2. Flash the 
3. If the ESP32 isn't connected to a known network, it makes its own named `Stikka-XXXXXX`.
4. Connect to it using password `stikkaesp32`.
5. The WebUI is on IP `1.2.3.4`. It should lead you through the setup process.
   - MQTT settings for [stikka-factory.github.io/stikka-mqtt](https://stikka-factory.github.io/stikka-mqtt/) are already set up.
6. Don't forget to give it a name, the default name is ignored.

## Removing a printer

There's no manual "forget" step either — a printer drops off the list on its own once it stops publishing status for 5 minutes straight (powered off, disconnected, etc).






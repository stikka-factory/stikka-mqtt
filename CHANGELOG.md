# Changelog

All notable changes to **Stikka-MQTT** are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
There are no tagged releases yet, so entries are grouped by month.

---

## [Unreleased]

### Fixed
- Docs: `CLAUDE.md` rewritten to match the current repo (no `esp32/` folder,
  no Python backend); README gained a "How to print stuff" guide; Seiko
  printer name corrected from "SPL" to "SLP".

---

## 2026-09

### Added
- "Download firmware.bin" button in the ESP32 Flasher tab (for updating
  through the bridge's own web UI); ESP32-S3 datasheet added to the
  firmware assets.
- About tab shows the real `README.md`; longer docs split out into
  `README_DETAILS.md`.

### Changed
- New `static-config.ts` defaults for app name, ZPL example and cable-label
  template.

## 2026-08

### Added
- `#<printer-name>` in the URL preselects a printer on the Label tab.
- Multiple text elements per label.
- Barcode label text under generated barcodes.
- Dark and "haxor" themes.
- ZPL over USB as a supported printer connection.

### Changed
- ESP32 firmware moved to its own repo,
  [stikka-esp32](https://github.com/stikka-factory/stikka-esp32).
- Firmware MQTT client switched to espMqttClient; print jobs are sent as a
  single MQTT message (chunking removed).
- Preview rendering improvements.
- Firmware is built by the Pages deploy job straight from
  `stikka-factory/stikka-esp32`, so the flasher always serves current builds.
- Fixed production `config.json` 404 (Vite `base` needs its trailing slash).

## 2026-07

### Added
- Static GitHub Pages deployment: the browser renders labels and publishes
  jobs over MQTT to an ESP32 bridge, no server needed.
- Supabase backing store for shared fonts, print statistics and discovered
  printers (`supabase/schema.sql`), live via Realtime.
- Brother QL support: the frontend builds the full QL raster stream and the
  bridge forwards it over USB host.
- Seiko SLP raster builder in the frontend (no firmware support yet).
- In-browser ESP32 web flasher with board/protocol/method selection.
- Printer location field; printers that stop reporting for 5 minutes drop off
  the list.
- Fork-me-on-GitHub ribbon.

### Changed
- App config (`config.json`) is generated at deploy time from repo
  Variables/Secrets; the in-app settings editor was removed.
- Endless ZPL labels get a 3 mm top/bottom border.

---

## Before 2026-07

Stikka started as a reimagination of
[printit](https://github.com/5shekel/printit): a Python app (first NiceGUI,
later FastAPI) with server-side rendering and USB/network printer drivers for
Zebra ZPL, Brother QL and Seiko SLP. That code is not part of this repo.

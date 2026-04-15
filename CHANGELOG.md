# Changelog

All notable changes to **Stikka-NG** are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Added
- `stikka.py` – clean application entry point; handles config loading,
  stats initialisation, fonts-preview generation and NiceGUI startup.
- `stikka_label_helper.py` – consolidated image/label creation module
  (replaces `label_helper.py`, absorbs rendering functions from `main.py`).
  - `list_fonts()` – discovers custom and system fonts.
  - `generate_fonts_preview()` – renders a JPEG sheet of all available fonts.
  - `calculate_text_height_mm()` – estimates label height from text for
    continuous-roll printers.
  - `render_preview()` – full label render pipeline (resize → text overlay →
    optional dither).
  - Full docstrings on every public function.
- `stikka_print_it.py` – consolidated printer driver module
  (replaces `print_it.py`).
  - `img_to_zpl()` – PIL image → ZPL command string.
  - `get_zpl_preview()` – ZPL → preview image via Labelary REST API.
  - `print_zpl()` – send ZPL over a raw TCP socket.
  - `print_ql()` – Brother QL raster print via brother_ql.
  - `print_seiko()` – Seiko SLP raw USB raster print via pyusb.
  - Full docstrings on every public function.
- `stikka_webui_handler.py` – `HomepageHandlers` class that owns all NiceGUI
  event callbacks, keeping layout code separate from business logic.
- `stikka_webui.py` – NiceGUI page definitions (`/` and `/config`),
  configuration management, and print-statistics helpers.
- `pyusb>=1.0.0` added to `pyproject.toml` dependencies.

### Changed
- Seiko SLP printing: USB interface is now explicitly claimed with
  `usb.util.claim_interface()` and always released in a `try/finally` block
  (`usb.util.release_interface()` + `usb.util.dispose_resources()`), fixing
  an *"[Errno 16] Resource busy"* error on the second and subsequent prints.
- Seiko SLP image conversion: padding bits in the last byte of each raster
  row are now masked back to 0 after bit inversion, eliminating a black
  stripe artefact at the right edge of printed images.

---

## [0.1.0] – Initial release

### Added
- NiceGUI web UI for label design and printing.
- Multi-printer support: file (debug download), ZPL (Zebra / network),
  Brother QL (USB via brother_ql), Seiko SLP (USB via pyusb).
- Image sources: random cat (The Cat API), random dog (Dog CEO API),
  file upload (images + PDF via pypdfium2), webcam capture with countdown.
- Text overlay: word-wrap, horizontal/vertical alignment, pixel offsets,
  rotation, outline, black/white fill, configurable font.
- Image adjustments: resize, crop-to-fill / letterbox, offset, rotate,
  black/white point, contrast, Floyd-Steinberg dithering preview.
- Font discovery from a custom directory and optionally system font dirs.
- Raw ZPL editor with live preview via the Labelary API.
- Print statistics tracked in a CSV file.
- Password-protected JSON configuration editor at `/config`.
- Systemd service unit (`stikka-NG.service`).

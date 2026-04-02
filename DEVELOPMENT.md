# Stikka NG – Development Guide

## Overview

**Stikka NG** is a ReactPy-based web UI for batch-printing customizable labels via Brother QL and ZPL printers. The app provides:
- Image + text overlay label composition
- Live preview rendering
- Printer discovery & configuration management
- Print job queueing

---

## Project Structure

### `/webui/stikka_factory/`

**Main application entry point**

- **`stikka_factory.py`** – Root `App()` component
  - Manages all global state (printer selection, media properties, text overlay, config lock)
  - Handles print job submission on background threads
  - Renders two-tab interface: "Label" and "Config"

- **`tabs/`** – UI tab implementations
  - **`tab_media.py`** – The main "Label" tab
    - Image controls: URL input, file upload, fetch cat/dog, white background
    - Text overlay controls: multi-line textarea, font, color, alignment, size, edge offset
    - Live preview using PIL image rendering
    - CSS grid layout: 3 columns, foldouts span full width, controls are 1/3 each
  
  - **`tab_config.py`** – The "Config" tab
    - Password-protected JSON editor for printer configuration file
    - Save / Reload / Reload Printers buttons
  
  - **`webui_common.py`** – Shared utilities
    - **Printer helpers**: `get_printer_dpi()`, `get_printer_label_width_mm()`, `get_printer_printable_width_px()`, `scan_printers()`
    - **Image pipeline**: `process_image_for_label()` (levels, contrast, dithering), `format_preview_to_media()` (scaling & centering)
    - **Text overlay**: `draw_overlay_text()` with multi-line wrap, vertical/horizontal alignment, edge offset
    - **Uploads**: `image_from_uploaded_payload()` — decodes browser file inputs from multiple payload formats
    - **UI components**: `PrinterSection`, `StatusSection`, `PreviewSection`, `ImageAdjustControls`
    - **CSS & font**: Injects stylesheet + base64-embedded 5x5-Tami font into the DOM at runtime

---

## CSS Architecture

### File: `/webui/style/styles.css`

All CSS is injected inline at runtime via `html.style(CSS_TEXT)` in `webui_common.py`. This means **relative URLs do not resolve** — all resources (including fonts) must be base64-encoded or use data URIs.

#### Color System

All colors are defined as CSS custom properties in `:root {}`:
- **Backgrounds**: `--bg-grad-start`, `--bg-grad-end`, `--panel`, `--panel-alt`, `--status-panel`
- **Typography**: `--ink` (primary), `--muted-ink` (secondary)
- **Fields**: `--field-bg`, `--field-border`
- **Accent**: `--accent` (orange-red, used for buttons, active tabs, focus rings)
- **Danger**: `--danger-bg`, `--danger-border`, `--danger-text`
- **Radii**: `--radius-xl`, `--radius-lg`, `--radius-md`, `--radius-sm`

To retheme, change only the `:root` CSS variables.

#### Layout Sections

1. **RESET & BASE** – Global box-sizing, body styling, animation keyframes
2. **APP SHELL & HERO** – Container, card, banner, title (rainbow gradient), subtitle
3. **TABS** – Tab bar, buttons, content panels (toggled via inline `display` style)
4. **PRINTER TOOLBAR** – Printer selector + scan button
5. **FORM PRIMITIVES** – Input, select, textarea, checkbox, range slider styles
6. **BUTTONS** – `.btn`, `.scan-btn`, `.print-btn`, `.foldout-action-btn`
7. **FOLDOUTS** – `<details>/<summary>` expand/collapse panels with custom arrow
8. **MEDIA TAB LAYOUT** – 3-column grid; foldouts span full width, controls 1/3 each per cell
9. **PREVIEW & SETTINGS CARDS** – Preview image + settings info side-by-side
10. **STATUS BAR** – Status message + print button
11. **CONFIG TAB** – 2-column layout (action buttons left, JSON editor right)
12. **RESPONSIVE OVERRIDES** – Media queries for tablets & phones

#### Removed Unused Classes

The following dead CSS was cleaned up:
- `.app-badge`, `.font-preview`, `.font-option`, `.image-preview-container`, `.cat-image`, `.overlay-grid`, `.form-grid`

---

## Key Features & Implementation

### 1. Image Processing Pipeline

**File**: `webui/stikka_factory/tabs/webui_common.py`

```python
process_image_for_label(image, black_point=32, white_point=224, contrast=1.2, label_width=None)
```

Converts any PIL image into a monochrome-dithered version suitable for thermal label printers:
1. Flatten RGBA to white background
2. Scale to label width while preserving aspect
3. Levels: clip darkest to `black_point`, brightest to `white_point`
4. Histogram equalization
5. Contrast enhancement
6. Floyd-Steinberg dithering
7. Return RGB (dithered) image

### 2. Text Overlay Rendering

**File**: `webui/stikka_factory/tabs/webui_common.py`

```python
draw_overlay_text(image, overlay_text="", selected_font="", text_size=36,
                  text_black=False, align="center", vertical_align="center", edge_offset=20)
```

Renders multiline text with:
- **Line wrapping**: `textwrap.wrap()` respects character width estimates
- **Empty line preservation**: blank input lines produce vertical spacing  
- **Alignment**: `left`, `center`, `right` (horizontal) × `top`, `center`, `bottom` (vertical)
- **Edge offset**: minimum padding in pixels from image edges
- **Stroke**: white text with black outline (or solid black if `text_black=True`)

### 3. Image Scaling & Format

**File**: `webui/stikka_factory/tabs/webui_common.py`

```python
format_preview_to_media(image, label_width_px, label_length_px=None, rotate=False, crop_to_center=False)
```

Fits image into media frame:
- **Endless media** (no `label_length_px`): scale to width, preserve height
- **Fixed media** (with `label_length_px`):
  - If `crop_to_center=False`: scale largest dimension to fit, center on white canvas
  - If `crop_to_center=True`: scale smallest dimension to fill, center-crop

**Rotation** (new): Optional `-90°` rotation before scaling.

### 4. Browser File Upload Handling

**File**: `webui/stikka_factory/tabs/tab_media.py`, function `_extract_upload_payload()`

Handles variable payload shapes from ReactPy browser file event:
- Detects data URLs, base64 strings, byte arrays, nested dict/list structures
- Attempts smart downscaling in browser (JS, max 1600px dimension)
- Returns JPEG for photos (smaller), PNG for transparent images

### 5. Printer Discovery

**File**: `webui/stikka_factory/tabs/webui_common.py`

```python
scan_printers()
```

- Loads configured printers from `printers_config.json`
- Auto-discovers Brother printers via `BrotherPrinter.find()`
- Auto-discovers ZPL printers via `ZPLPrinter.find()`
- Cleans up stale entries from the global `PRINTER_REGISTRY`
- Returns list of dicts: `{serial, type, label, model}`

### 6. Font Management

**File**: `webui/stikka_factory/tabs/webui_common.py`

Fonts are loaded from `/fonts/` directory at startup:
- OTF and TTF files are auto-discovered
- Default font is `Orbitron_Black.otf` (if available), else first by alphanumeric sort
- Selected font path is passed to PIL `ImageFont.truetype()`

The **5x5-Tami** pixel font for the app title is base64-embedded in CSS at runtime:
```python
_embedded_tami_font_face_css()  # Returns @font-face with data: URL
```

---

## Data Flow: From Label to Print

1. **User composes label**:
   - Selects/uploads/fetches image
   - Enters text overlay
   - Adjusts image (rotation, crop, black point, contrast)
   - Adjusts text (font, size, alignment, color)

2. **Live preview renders**:
   - `process_image_for_label()` — apply levels + dither
   - `draw_overlay_text()` — render text on image
   - `format_preview_to_media()` — scale/center to media size
   - Convert to PNG base64 → display in `<img>` tag

3. **User clicks Print**:
   - Printer dimensions fetched from `PRINTER_REGISTRY` status
   - Same pipeline applied at full print resolution
   - `StikkaLabel` object created with processed image
   - `BrotherPrintJob` or `ZPLPrintJob` queued on printer
   - Threaded background task → `set_status_message()` on completion/error

---

## State Management (ReactPy Hooks)

All state is in the `App()` component (no Redux/Redux-like library):

**Printer state**:
- `active_tab` — "simple" or "config"
- `selected_serial` — currently selected printer serial number
- `printer_options` — list from `scan_printers()`
- `status_message` — user-facing status text
- `is_printing` — bool to disable print button during job

**Label state** (MediaTab):
- `media_url` — image URL
- `media_uploaded_payload` — base64 upload data
- `media_use_white_background` — bool
- `media_crop_to_center` — bool
- `media_rotate_image` — bool (rotate image -90°)
- `media_overlay_text` — multiline text
- `media_text_black` — bool (black vs. white+outline)
- `media_text_align` — "left", "center", "right"
- `media_text_vertical_align` — "top", "center", "bottom"
- `media_text_edge_offset` — pixel distance from edge
- `media_font` — selected font filename
- `media_text_size` — font size in pixels
- `media_black_point`, `media_white_point`, `media_contrast` — image adjustment

**Config state** (ConfigTab):
- `config_password_input` — password field
- `config_unlocked` — bool (can edit/save config)
- `config_text` — JSON string from `printers_config.json`

---

## Responsive Design

### 900px breakpoint
- Reduce padding
- Stack preview + settings cards vertically

### 600px breakpoint
- Foldout grids → 1 column (instead of 3)
- Image/text control placement → auto (reset explicit grid rows/cols)
- Tab buttons smaller
- Printer toolbar → vertical stack
- All buttons → full width

---

## File Deletions & Cleanup _(Recent)_

**Removed**:
- `/webui/stikka_factory/tabs/tab_simple.py` — Unused `SimpleLabel` component (never imported)
- **Unused CSS classes**: `.app-badge`, `.font-preview`, `.font-option`, `.form-grid`, `.overlay-grid`, `.image-preview-container`, `.cat-image`

---

## Configuration

### Environment Variables

- `STIKKA_CONFIG_PASSWORD` (default: `"stikka"`) — password to unlock config tab

### Config File

**`printers_config.json`** — JSON array of printer definitions:
```json
{
  "printers": [
    {
      "serial_number": "...",
      "ip_address": "...",
      "port": 9100,
      "type": "zpl"
    }
  ]
}
```

---

## Running

```bash
# Install dependencies
uv sync

# Run the app (starts ReactPy server)
uv run stikka_factory.py
```

The app is accessible at `http://localhost:8000` (or similar).

---

## Troubleshooting

### Font not loading for app title
The 5x5-Tami font is **only available at runtime** when CSS is injected.  Static `@font-face` rules with file paths don't work in injected stylesheets.

### Printer not discovered  
1. Check printer is powered on and connected (USB or network)
2. Run "Scan printers" button
3. Check `printers_config.json` for manual entries
4. Check `~/stikka.log` for debugging output

### Image rotates unexpectedly  
The "Rotate image" checkbox is now **explicit**. No automatic rotation is performed. Check if accidentally toggled.

### Long text lines cut off  
The text overlay uses `textwrap.wrap()` with character-width estimation. Adjust `media_text_size` if text is too tight or adjust `media_text_edge_offset` for more breathing room.

---

## Useful Reference Commands

```bash
# Run tests
uv run pytest

# Format code
uvx black .

# Lint
uvx ruff check .

# Check printer config
cat printers_config.json | jq '.'

# Monitor logs
tail -f ~/stikka.log
```

---

Generated: repository cleanup & documentation pass  
Last updated: CSS refactor (removed dead classes, added color tokens section)

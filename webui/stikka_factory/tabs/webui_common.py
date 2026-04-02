"""Shared utilities for the Stikka Factory web UI.

This module provides:
  - CSS loading with base64-embedded custom font (Tami5x5).
  - Printer discovery and status helpers.
  - Image processing pipeline (levels, contrast, dithering).
  - Text overlay rendering with multi-line wrapping and alignment.
  - Reusable ReactPy UI components: PrinterSection, StatusSection,
    PreviewSection, ImageAdjustControls.
  - The global PRINTER_REGISTRY instance shared across the app.
"""

import base64
import json
from io import BytesIO
from pathlib import Path
import re
from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps
import urllib.request
from brother_ql import labels

from reactpy import component, html

from labelprinter.printer_ql import BrotherPrinter
from labelprinter.printer_zpl import ZPLPrinter
from ...registry import PrinterRegistry
from .. import image_utls
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
import logger

log = logger.log

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FONT_DIR = PROJECT_ROOT / "fonts"
CSS_PATH = PROJECT_ROOT / "webui" / "style" / "styles.css"


def _embedded_tami_font_face_css():
    """Return a CSS @font-face block for the 5x5 Tami font, base64-encoded.

    The font is embedded directly in the CSS string so it works when the
    stylesheet is injected inline by ReactPy (which cannot resolve file-relative
    URLs at runtime).

    Returns an empty string if the font file is missing.
    """
    font_path = FONT_DIR / "5x5-Tami.ttf"
    if not font_path.exists():
        return ""
    try:
        encoded = base64.b64encode(font_path.read_bytes()).decode("ascii")
    except OSError:
        return ""
    return (
        '@font-face {'
        'font-family: "Tami5x5";'
        'src: url("data:font/ttf;base64,' + encoded + '") format("truetype");'
        'font-display: swap;'
        '}\n'
    )


try:
    CSS_TEXT = _embedded_tami_font_face_css() + CSS_PATH.read_text(encoding="utf-8")
except OSError:
    CSS_TEXT = _embedded_tami_font_face_css()

FONT_OPTIONS = sorted(
    file.name
    for file in FONT_DIR.iterdir()
    if file.is_file() and file.suffix.lower() in {".otf", ".ttf"}
)
DEFAULT_FONT = "Orbitron_Black.otf" if "Orbitron_Black.otf" in FONT_OPTIONS else (
    FONT_OPTIONS[0] if FONT_OPTIONS else "")

DEFAULT_FORM = {
    "name": "",
    "street": "",
    "zip_code": "",
    "city": "",
    "country": "",
}

PRINTER_REGISTRY = PrinterRegistry()
_IMAGE_CACHE = {}


def get_printer_label_width_mm(printer, default_width=62):
    """Return the media width in mm for the given printer, or *default_width*."""
    if printer is None:
        return default_width
    try:
        width_mm = int(getattr(printer.status, "media_width", default_width))
        return width_mm if width_mm > 0 else default_width
    except Exception:
        return default_width


def get_printer_label_length_mm(printer):
    """Return the die-cut label length in mm, or None for endless media."""
    if printer is None:
        return None
    try:
        length_mm = int(getattr(printer.status, "media_length", 0))
        return length_mm if length_mm > 0 else None
    except Exception:
        return None


def get_printer_media_label(printer):
    """Return a human-readable media size string, e.g. '62x100 mm' or '62 mm endless'."""
    width_mm = printer.status.media_width or get_printer_label_width_mm(printer) or "Unknown"
    length_mm = printer.status.media_length or get_printer_label_length_mm(printer) or None

    if length_mm:
        return f"{width_mm}x{length_mm} mm"
    return f"{width_mm} mm endless"


def get_printer_type_name(printer):
    """Return a short type string: 'brother', 'zpl', or 'unknown'."""
    if isinstance(printer, BrotherPrinter):
        return "brother"
    if isinstance(printer, ZPLPrinter):
        return "zpl"
    return "unknown"


def get_printer_dpi(printer, default_dpi=300):
    """Return the printer's dots-per-inch, falling back to *default_dpi* (300)."""
    if printer is None:
        return default_dpi
    try:
        dpi = int(getattr(printer.status, "dpi", default_dpi))
        log.info(f"Detected printer DPI: {dpi}")
        return dpi if dpi > 0 else default_dpi
    except Exception:
        return default_dpi


def get_printer_printable_width_px(printer, default_width=696):
    """Return the number of printable pixels across the label width.

    Tries to match the printer's media identifier against the brother_ql label
    catalogue first (most accurate).  Falls back to computing from the width in
    mm and the detected DPI.  Returns *default_width* if both methods fail.
    """
    label_identifier_candidates = []

    try:
        media_name = str(
            getattr(printer.status, "media_name", "") or "").strip()
        if media_name:
            label_identifier_candidates.append(media_name)
    except Exception:
        pass

    try:
        media_width = str(
            getattr(printer.status, "media_width", "") or "").strip()
        if media_width:
            label_identifier_candidates.append(media_width)
    except Exception:
        pass

    for candidate in label_identifier_candidates:
        for label in labels.ALL_LABELS:
            if label.identifier == candidate:
                return int(label.dots_printable[0])

    try:
        width_mm = get_printer_label_width_mm(printer)
        dpi = get_printer_dpi(printer)
        return max(1, int(round((width_mm / 25.4) * dpi)))
    except Exception:
        return default_width


def fetch_image_from_url(url, timeout=10):
    """Download an image from *url* and return it as a PIL RGB Image.

    Results are cached in-memory by URL so repeated identical requests during
    the same server session do not incur additional network round-trips.
    """
    if url in _IMAGE_CACHE:
        return Image.open(BytesIO(_IMAGE_CACHE[url])).convert("RGB")

    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0 (compatible; Stikka-NG/1.0)")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read()
    _IMAGE_CACHE[url] = data
    return Image.open(BytesIO(data)).convert("RGB")


def image_from_uploaded_payload(payload):
    """Decode uploaded file payloads from ReactPy events into a PIL image."""
    if not payload:
        raise ValueError("No upload payload provided")

    def _decode_base64(value):
        text = value.strip()
        if "," in text and text.startswith("data:"):
            text = text.split(",", 1)[1]
        text = text.strip()
        pad = len(text) % 4
        if pad:
            text += "=" * (4 - pad)
        try:
            return base64.b64decode(text)
        except Exception:
            try:
                return base64.urlsafe_b64decode(text)
            except Exception as exc:
                raise ValueError(f"Invalid base64 upload payload: {exc}") from exc

    def _looks_like_base64_string(value):
        if not isinstance(value, str):
            return False
        text = value.strip()
        if len(text) < 128:
            return False
        if any(ch.isspace() for ch in text):
            return False
        return re.fullmatch(r"[A-Za-z0-9+/=_-]+", text) is not None

    def _extract_raw(obj):
        if obj is None:
            return None

        if isinstance(obj, (bytes, bytearray)):
            return bytes(obj)
        if isinstance(obj, list):
            if obj and all(isinstance(item, int) for item in obj):
                return bytes(obj)
            for item in obj:
                found = _extract_raw(item)
                if found:
                    return found
            return None
        if isinstance(obj, str):
            text = obj.strip()
            maybe_path = Path(text)
            if maybe_path.exists() and maybe_path.is_file():
                return maybe_path.read_bytes()
            if text.startswith("data:image"):
                return _decode_base64(text)
            if _looks_like_base64_string(text):
                return _decode_base64(text)
            return None
        if isinstance(obj, dict):
            for key in ["data_url", "data", "content", "base64", "file", "blob", "path", "tempfile", "value", "result"]:
                if key in obj and obj[key] is not None:
                    found = _extract_raw(obj[key])
                    if found:
                        return found
            return None
        return None

    raw = _extract_raw(payload)

    if not raw:
        raise ValueError("Empty or unsupported upload payload")

    return Image.open(BytesIO(raw)).convert("RGB")


def process_image_for_label(image, black_point=32, white_point=224, contrast=1.2, label_width=None):
    """Prepare a PIL image for monochrome label printing.

    Processing pipeline:
      1. Flatten alpha to white background (if RGBA).
      2. Scale to *label_width* pixels wide while preserving aspect ratio.
      3. Convert to grayscale and apply level clipping (black_point / white_point).
      4. Histogram equalisation.
      5. Contrast enhancement.

    Returns a contrast-enhanced RGB PIL Image (dithering applied after final scaling).
    """
    black_point = int(max(0, min(254, black_point)))
    white_point = int(max(1, min(255, white_point)))
    if white_point <= black_point:
        white_point = min(255, black_point + 1)

    # Keep alpha uploads predictable when compositing for print.
    if image.mode == "RGBA":
        background = Image.new("RGBA", image.size, "white")
        image = Image.alpha_composite(background, image).convert("RGB")

    if label_width and image.width != label_width:
        new_height = int((label_width / image.width) * image.height)
        image = image.resize((label_width, new_height), Image.LANCZOS)

    gray = image.convert("L")
    leveled = image_utls.apply_levels(
        gray, black_point=black_point, white_point=white_point)
    equalized = ImageOps.equalize(leveled)
    contrasted = ImageEnhance.Contrast(equalized).enhance(float(contrast))
    return contrasted.convert("RGB")


def format_preview_to_media(
    image,
    label_width_px,
    label_length_px=None,
    rotate=False,
    crop_to_center=False,
    image_offset_x=0,
    image_offset_y=0,
):
    """Fit a processed image into the selected media preview frame and apply dithering.

    For endless media (label_length_px is None), only width is enforced.
    For fixed-length media, image is centered on a white canvas of exact media size.
    Floyd-Steinberg dithering is applied as the final step after all scaling.
    """
    if rotate:
        image = image.rotate(-90, expand=True)

    target_width = int(label_width_px) if label_width_px else image.width
    target_height = int(label_length_px) if label_length_px else None

    # Endless media: only fit width while preserving aspect.
    if not target_height or target_height <= 0:
        if target_width and image.width != target_width:
            new_height = int((target_width / image.width) * image.height)
            resized = image.resize((target_width, max(1, new_height)), Image.LANCZOS)
            if image_offset_x or image_offset_y:
                endless_canvas = Image.new("RGB", resized.size, "white")
                endless_canvas.paste(resized, (int(image_offset_x), int(image_offset_y)))
                resized = endless_canvas
            # Apply Floyd-Steinberg dithering as final step after scaling
            dithered = resized.convert("1", dither=Image.FLOYDSTEINBERG)
            return dithered.convert("RGB")
        if image_offset_x or image_offset_y:
            endless_canvas = Image.new("RGB", image.size, "white")
            endless_canvas.paste(image, (int(image_offset_x), int(image_offset_y)))
            image = endless_canvas
        # Apply Floyd-Steinberg dithering even if no resize needed
        dithered = image.convert("1", dither=Image.FLOYDSTEINBERG)
        return dithered.convert("RGB")

    if crop_to_center:
        scale = max(target_width / image.width, target_height / image.height)
    else:
        scale = min(target_width / image.width, target_height / image.height)
    fit_w = max(1, int(round(image.width * scale)))
    fit_h = max(1, int(round(image.height * scale)))
    fitted = image.resize((fit_w, fit_h), Image.LANCZOS)

    canvas = Image.new("RGB", (target_width, target_height), "white")
    offset_x = ((target_width - fitted.width) // 2) + int(image_offset_x)
    offset_y = ((target_height - fitted.height) // 2) + int(image_offset_y)
    canvas.paste(fitted, (offset_x, offset_y))
    
    # Apply Floyd-Steinberg dithering as final step after all scaling
    dithered = canvas.convert("1", dither=Image.FLOYDSTEINBERG)
    return dithered.convert("RGB")


def draw_overlay_text(
    image,
    overlay_text="",
    selected_font="",
    text_size=36,
    text_black=False,
    align="center",
    vertical_align="center",
    offset_x=0,
    offset_y=0,
    rotate_90=False,
):
    draw = ImageDraw.Draw(image)
    try:
        font_path = str(FONT_DIR / selected_font) if selected_font else None
        font = ImageFont.truetype(font_path, size=max(12, int(text_size))) if font_path else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    stroke_width = max(1, int(round(max(12, int(text_size)) / 16)))
    text = (overlay_text or "").strip()
    if not text:
        return image

    raw_lines = text.split("\n")

    try:
        ascent, descent = font.getmetrics()
        base_line_height = ascent + descent
    except Exception:
        bbox = font.getbbox("Ag")
        base_line_height = max(1, bbox[3] - bbox[1])
    line_height = max(1, base_line_height + max(2, int(text_size * 0.12)))

    fill_color = "black" if text_black else "white"
    stroke_color = None if text_black else "black"
    applied_stroke_width = 0 if text_black else stroke_width

    usable_width = max(1, image.width - 24)

    def _measure_width(value):
        if not value:
            return 0.0
        try:
            return float(draw.textlength(value, font=font)) + (applied_stroke_width * 2)
        except Exception:
            bbox = font.getbbox(value)
            return float(max(0, bbox[2] - bbox[0])) + (applied_stroke_width * 2)

    def _split_long_token(token):
        chunks = []
        remaining = token
        while remaining and _measure_width(remaining) > usable_width:
            split_at = 1
            for idx in range(1, len(remaining) + 1):
                if _measure_width(remaining[:idx]) <= usable_width:
                    split_at = idx
                else:
                    break
            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:]
        if remaining:
            chunks.append(remaining)
        return chunks

    wrapped_lines = []
    for raw_line in raw_lines:
        if raw_line == "":
            wrapped_lines.append("")
            continue

        tokens = re.findall(r"\S+\s*|\s+", raw_line)
        current = ""
        line_parts = []

        for token in tokens:
            candidate = current + token
            if _measure_width(candidate) <= usable_width or current == "":
                current = candidate
                continue

            if current.strip():
                line_parts.append(current.rstrip())

            token = token.lstrip()
            if token and _measure_width(token) > usable_width:
                chunks = _split_long_token(token)
                line_parts.extend(chunks[:-1])
                current = chunks[-1]
            else:
                current = token

        if current.strip():
            line_parts.append(current.rstrip())

        wrapped_lines.extend(line_parts or [""])

    total_height = line_height * len(wrapped_lines)
    if vertical_align == "top":
        top_y = 0
    elif vertical_align == "bottom":
        top_y = max(0, image.height - total_height)
    else:
        top_y = max(0, (image.height - total_height) // 2)

    if align == "left":
        x = 0
        anchor = "la"
    elif align == "right":
        x = image.width
        anchor = "ra"
    else:
        x = image.width // 2
        anchor = "ma"

    x += int(offset_x)
    top_y += int(offset_y)

    if rotate_90:
        # Draw on a padded canvas before rotation so edge-aligned text is not clipped.
        pad_x = image.width
        pad_y = image.height
        text_layer = Image.new("RGBA", (image.width + (2 * pad_x), image.height + (2 * pad_y)), (0, 0, 0, 0))
        layer_draw = ImageDraw.Draw(text_layer)
        layer_x = x + pad_x
        layer_top_y = top_y + pad_y
        for idx, line in enumerate(wrapped_lines):
            y = layer_top_y + (idx * line_height)
            if line == "":
                continue
            layer_draw.text(
                (layer_x, y),
                line,
                fill=fill_color,
                font=font,
                anchor=anchor,
                stroke_width=applied_stroke_width,
                stroke_fill=stroke_color,
            )

        rotated_layer = text_layer.rotate(-90, expand=False)
        cropped_layer = rotated_layer.crop((pad_x, pad_y, pad_x + image.width, pad_y + image.height))
        composed = Image.alpha_composite(image.convert("RGBA"), cropped_layer)
        image.paste(composed.convert("RGB"))
    else:
        for idx, line in enumerate(wrapped_lines):
            y = top_y + (idx * line_height)
            if line == "":
                continue
            draw.text(
                (x, y),
                line,
                fill=fill_color,
                font=font,
                anchor=anchor,
                stroke_width=applied_stroke_width,
                stroke_fill=stroke_color,
            )

    return image


@component
def ImageAdjustControls(black_point, set_black_point, white_point, set_white_point, contrast, set_contrast):
    def on_black_change(event):
        set_black_point(int(event["target"]["value"]))

    def on_white_change(event):
        set_white_point(int(event["target"]["value"]))

    def on_contrast_change(event):
        set_contrast(float(event["target"]["value"]))

    return html.div(
        {"class_name": "image-adjustments"},
        html.label(
            {"class_name": "form-field"},
            html.div(
                {"class_name": "range-head"},
                html.span({"class_name": "field-label"}, "Black point"),
                html.span({"class_name": "range-value"}, str(black_point)),
            ),
            html.input(
                {
                    "type": "range",
                    "min": "0",
                    "max": "254",
                    "step": "1",
                    "value": str(black_point),
                    "onChange": on_black_change,
                    "class_name": "range-control",
                }
            ),
        ),
        html.label(
            {"class_name": "form-field"},
            html.div(
                {"class_name": "range-head"},
                html.span({"class_name": "field-label"}, "White point"),
                html.span({"class_name": "range-value"}, str(white_point)),
            ),
            html.input(
                {
                    "type": "range",
                    "min": "1",
                    "max": "255",
                    "step": "1",
                    "value": str(white_point),
                    "onChange": on_white_change,
                    "class_name": "range-control",
                }
            ),
        ),
        html.label(
            {"class_name": "form-field"},
            html.div(
                {"class_name": "range-head"},
                html.span({"class_name": "field-label"}, "Contrast"),
                html.span({"class_name": "range-value"}, f"{contrast:.2f}x"),
            ),
            html.input(
                {
                    "type": "range",
                    "min": "0.5",
                    "max": "3.0",
                    "step": "0.05",
                    "value": str(contrast),
                    "onChange": on_contrast_change,
                    "class_name": "range-control",
                }
            ),
        ),
    )


def scan_printers():
    log.info("Scanning for printers...")
    config_file = PROJECT_ROOT / "printers_config.json"

    active_serials = set()
    if config_file.exists():
        try:
            log.info(f"Loading printer config from {config_file}")
            raw = json.loads(config_file.read_text(encoding="utf-8"))
            for p in raw.get("printers", []):
                sn = p.get("serial_number")
                if sn:
                    active_serials.add(sn)
        except Exception as exc:
            log.warning(f"Failed to parse printer config: {exc}")

    discovered = {}
    try:
        brother_discovered = BrotherPrinter.find()
        discovered.update(brother_discovered)
        active_serials.update(brother_discovered.keys())
    except Exception as exc:
        log.warning(f"Failed to discover Brother printers: {exc}")

    try:
        zpl_discovered = ZPLPrinter.find()
        for printer in zpl_discovered:
            serial = getattr(printer, "serial_number", None)
            if not serial:
                continue
            discovered[serial] = printer
            active_serials.add(serial)
    except Exception as exc:
        log.warning(f"Failed to discover ZPL printers: {exc}")

    for serial in list(PRINTER_REGISTRY.get_all_printers().keys()):
        if serial not in active_serials:
            PRINTER_REGISTRY.remove_printer(serial)

    if config_file.exists():
        PRINTER_REGISTRY.load_from_config(str(config_file))
    if discovered:
        PRINTER_REGISTRY.register_printers(discovered)

    printers = PRINTER_REGISTRY.get_all_printers()
    results = []
    for serial, printer in printers.items():
        results.append(
            {
                "serial": serial,
                "type": get_printer_type_name(printer),
                "label": get_printer_media_label(printer),
                "model": getattr(printer, "model", "Unknown"),
            }
        )

    return results


def render_preview_src(image_obj):
    buffer = BytesIO()
    image_obj.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def make_field(label_text, field_name, value, placeholder, on_change, field_type="text"):
    return html.label(
        {"class_name": "form-field"},
        html.span({"class_name": "field-label"}, label_text),
        html.input(
            {
                "type": field_type,
                "value": value,
                "placeholder": placeholder,
                "onChange": on_change(field_name) if callable(on_change) else on_change,
                "class_name": "input-control",
            }
        ),
    )


@component
def PrinterSection(on_scan, selected_serial, printer_options, on_printer_change):
    return html.div(
        {"class_name": "toolbar"},
        html.label(
            {"class_name": "form-field printer-field"},
            html.span({"class_name": "field-label"}, "Printer"),
            html.select(
                {
                    "value": selected_serial,
                    "onChange": on_printer_change,
                    "class_name": "input-control",
                },
                html.option({"value": ""}, "Select a printer"),
                *[
                    html.option(
                        {"key": option["serial"], "value": option["serial"]},
                        f"{option.get('model', 'Unknown')} - {option['serial']} - {option.get('label', 'N/A')}"
                    )
                    for option in printer_options
                ],
            ),
        ),
        html.button(
            {
                "onClick": on_scan,
                "class_name": "btn scan-btn",
            },
            "Scan printers",
        ),
    )


@component
def PreviewSection(preview_src, preview_error, title="Preview"):
    return html.div(
        {"class_name": "preview-card"},
        html.p({"class_name": "card-title"}, title),
        html.img(
            {
                "src": preview_src,
                "alt": "Label preview",
                "class_name": "preview-image",
            }
        ) if preview_src else html.div(
            {"class_name": "preview-error"},
            preview_error or "Preview unavailable."
        ),
    )


@component
def StatusSection(status_message, on_print, is_printing, print_label="Print Label"):
    print_btn_classes = "btn print-btn"
    if is_printing:
        print_btn_classes += " is-disabled"

    return html.div(
        {"class_name": "status-row"},
        html.div(
            html.strong({"class_name": "status-title"}, "Status"),
            html.p({"class_name": "status-message"}, status_message),
        ),
        html.button(
            {
                "onClick": on_print,
                "disabled": is_printing,
                "class_name": print_btn_classes,
            },
            "Printing..." if is_printing else print_label,
        ),
    )

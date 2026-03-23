import base64
import json
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageEnhance, ImageOps
import urllib.request
from brother_ql import labels

from reactpy import component, html

from printer_ql import BrotherPrinter
from printer_registry import PrinterRegistry
import image_utls
import logger

log = logger.log

FONT_DIR = Path(__file__).parent / "fonts"
CSS_PATH = Path(__file__).parent / "styles.css"
try:
    CSS_TEXT = CSS_PATH.read_text(encoding="utf-8")
except OSError:
    CSS_TEXT = ""

FONT_OPTIONS = sorted(
    file.name
    for file in FONT_DIR.iterdir()
    if file.is_file() and file.suffix.lower() in {".otf", ".ttf"}
)
DEFAULT_FONT = "Orbitron_Black.otf" if "Orbitron_Black.otf" in FONT_OPTIONS else (FONT_OPTIONS[0] if FONT_OPTIONS else "")

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
    try:
        width_mm = int(getattr(printer.status, "media_width", default_width))
        return width_mm if width_mm > 0 else default_width
    except Exception:
        return default_width


def get_printer_printable_width_px(printer, default_width=696):
    label_identifier_candidates = []

    try:
        media_name = str(getattr(printer.status, "media_name", "") or "").strip()
        if media_name:
            label_identifier_candidates.append(media_name)
    except Exception:
        pass

    try:
        media_width = str(getattr(printer.status, "media_width", "") or "").strip()
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
        return max(1, int(round((width_mm / 25.4) * 300)))
    except Exception:
        return default_width


def fetch_image_from_url(url, timeout=10):
    if url in _IMAGE_CACHE:
        return Image.open(BytesIO(_IMAGE_CACHE[url])).convert("RGB")

    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0 (compatible; Stikka-NG/1.0)")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read()
    _IMAGE_CACHE[url] = data
    return Image.open(BytesIO(data)).convert("RGB")


def process_image_for_label(image, black_point=32, white_point=224, contrast=1.2, label_width=None):
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
    leveled = image_utls.apply_levels(gray, black_point=black_point, white_point=white_point)
    equalized = ImageOps.equalize(leveled)
    contrasted = ImageEnhance.Contrast(equalized).enhance(float(contrast))
    dithered = contrasted.convert("1", dither=Image.FLOYDSTEINBERG)
    return dithered.convert("RGB")


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
    config_file = Path(__file__).parent / "printers_config.json"

    active_serials = set()
    if config_file.exists():
        try:
            raw = json.loads(config_file.read_text(encoding="utf-8"))
            for p in raw.get("printers", []):
                sn = p.get("serial_number")
                if sn:
                    active_serials.add(sn)
        except Exception as exc:
            log.warning(f"Failed to parse printer config: {exc}")

    discovered = {}
    try:
        discovered = BrotherPrinter.find()
        active_serials.update(discovered.keys())
    except Exception as exc:
        log.warning(f"Failed to discover printers: {exc}")

    for serial in list(PRINTER_REGISTRY.get_all_printers().keys()):
        if serial not in active_serials:
            PRINTER_REGISTRY.remove_printer(serial)

    if config_file.exists():
        PRINTER_REGISTRY.load_from_config(str(config_file))
    if discovered:
        PRINTER_REGISTRY.register_printers(discovered)

    printers = PRINTER_REGISTRY.get_all_printers()
    return [
        {
            "serial": serial,
            "model": printer.model,
            "media": printer.status.media_name,
        }
        for serial, printer in printers.items()
    ]


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
                        f"{option['serial']} - {option['model']} - tape {option['media']}"
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

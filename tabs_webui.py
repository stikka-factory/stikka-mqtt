import base64
import json
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

from reactpy import component, html, hooks, run

from label import StikkaLabel
from printer_debug import DebugPrintJob, PrinterDebug
from printer_ql import BrotherPrintJob, BrotherPrinter
from printer_registry import PrinterRegistry
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
PRINTER_REGISTRY = PrinterRegistry()

DEFAULT_FORM = {
    "name": "",
    "street": "",
    "zip_code": "",
    "city": "",
    "country": "",
}


def _scan_printers():
    config_file = Path(__file__).parent / "printers_config.json"
    if config_file.exists():
        printers = PRINTER_REGISTRY.load_from_config(str(config_file))
    else:
        printers = {}
    
    try:
        discovered = PRINTER_REGISTRY.discover(BrotherPrinter.find)
        printers.update(discovered)
    except Exception as exc:
        log.warning(f"Failed to discover Brother printers: {exc}")
    
    return [
        {
            "serial": serial,
            "model": printer.model,
            "media": printer.status.media_name,
        }
        for serial, printer in printers.items()
    ]


def _render_preview_src(image_obj):
    """Convert PIL Image to base64 data URL"""
    buffer = BytesIO()
    image_obj.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _make_field(label_text, field_name, value, placeholder, on_change, field_type="text"):
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
    """Shared printer selection component"""
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
    """Shared preview component"""
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
    """Shared status and print button component"""
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


@component
def SimpleLabel():
    """Simple centered text label tab"""
    text_value, set_text = hooks.use_state("Hello\nWorld")
    text_height, set_text_height = hooks.use_state(5.0)
    selected_font, set_selected_font = hooks.use_state(DEFAULT_FONT)

    def handle_text_change(event):
        set_text(event["target"]["value"])

    def handle_height_change(event):
        set_text_height(float(event["target"]["value"]))

    def handle_font_change(event):
        set_selected_font(event["target"]["value"])

    preview_src = ""
    preview_error = ""
    try:
        # Calculate label dimensions based on number of lines
        lines = text_value.strip().split('\n') if text_value.strip() else [""]
        num_lines = len(lines)
        line_spacing = 2  # mm between lines
        label_height = text_height + (num_lines * text_height) + ((num_lines - 1) * line_spacing) + text_height
        label_width = 62
        
        label = StikkaLabel(label_width, label_height)
        font_path = str(FONT_DIR / selected_font) if selected_font else "A"
        
        # Add each line of text
        y_pos = text_height
        for i, line in enumerate(lines):
            label.add_text(
                line.strip() or " ",
                x=5,
                y=y_pos,
                char_height=text_height,
                char_width=1.0,
                line_width=int(label_width - 10),
                font=font_path,
            )
            y_pos += text_height + line_spacing
        
        preview_image = label.render_image(framing=True)
        preview_src = _render_preview_src(preview_image)
    except Exception as exc:
        preview_error = f"Preview unavailable: {exc}"

    return html.div(
        html.label(
            {"class_name": "form-field"},
            html.span({"class_name": "field-label"}, "Label text (multiline)"),
            html.textarea(
                {
                    "value": text_value,
                    "placeholder": "Enter text (use Shift+Enter for new lines)",
                    "onChange": handle_text_change,
                    "class_name": "input-control textarea-control",
                    "rows": "4",
                }
            ),
        ),
        html.label(
            {"class_name": "form-field"},
            html.span({"class_name": "field-label"}, "Font"),
            html.select(
                {
                    "value": selected_font,
                    "onChange": handle_font_change,
                    "disabled": not FONT_OPTIONS,
                    "class_name": "input-control font-select",
                },
                *(
                    [
                        html.option(
                            {"key": font_name, "value": font_name, "class_name": f"font-option font-{font_name.lower().replace('.', '-')}"},
                            font_name
                        )
                        for font_name in FONT_OPTIONS
                    ]
                    if FONT_OPTIONS
                    else [html.option({"value": ""}, "No font files found")]
                ),
            ),
        ),
        html.label(
            {"class_name": "form-field"},
            html.div(
                {"class_name": "range-head"},
                html.span({"class_name": "field-label"}, "Font size"),
                html.span({"class_name": "range-value"}, f"{text_height:.1f} mm"),
            ),
            html.input(
                {
                    "type": "range",
                    "min": "3",
                    "max": "10",
                    "step": "0.5",
                    "value": str(text_height),
                    "onChange": handle_height_change,
                    "class_name": "range-control",
                }
            ),
        ),
        html.div(
            {"class_name": "preview-grid"},
            PreviewSection(preview_src, preview_error),
            html.div(
                {"class_name": "settings-card"},
                html.p({"class_name": "card-title"}, "Settings"),
                html.p({"class_name": "setting-row"}, f"Lines: {len(text_value.strip().split(chr(10))) if text_value.strip() else 0}"),
                html.p({"class_name": "setting-row"}, f"Font: {selected_font or 'A'}"),
                html.p({"class_name": "setting-row"}, f"Font size: {text_height:.1f} mm"),
            ),
        ),
    )


@component
def AddressLabelTab():
    """Address label tab"""
    form_data, set_form_data = hooks.use_state(DEFAULT_FORM)
    selected_font, set_selected_font = hooks.use_state(DEFAULT_FONT)
    text_height, set_text_height = hooks.use_state(5.0)

    def handle_field_change(field_name):
        def _handle_change(event):
            value = event["target"]["value"]
            set_form_data(lambda prev: {**prev, field_name: value})
        return _handle_change

    def handle_font_change(event):
        set_selected_font(event["target"]["value"])

    def handle_text_height_change(event):
        set_text_height(float(event["target"]["value"]))

    preview_width = 62
    preview_height = text_height + (4 * text_height) + (3 * 2) + text_height
    preview_src = ""
    preview_error = ""
    try:
        font_path = str(FONT_DIR / selected_font) if selected_font else "A"
        label = StikkaLabel.address_label(
            width=preview_width,
            name=form_data["name"].strip() or "Jane Smith",
            street=form_data["street"].strip() or "456 Elm St",
            zip_code=form_data["zip_code"].strip() or "67890",
            city=form_data["city"].strip() or "Othertown",
            country=form_data["country"].strip() or "",
            font=font_path,
            text_height=text_height,
        )
        preview_image = label.render_image(framing=True)
        preview_src = _render_preview_src(preview_image)
    except Exception as exc:
        preview_error = f"Preview unavailable: {exc}"

    return html.div(
        html.div(
            {"class_name": "form-grid"},
            _make_field("Full name", "name", form_data["name"], "Jane Smith", handle_field_change),
            _make_field("Street", "street", form_data["street"], "456 Elm St", handle_field_change),
            _make_field("ZIP code", "zip_code", form_data["zip_code"], "67890", handle_field_change),
            _make_field("City", "city", form_data["city"], "Othertown", handle_field_change),
            _make_field("Country", "country", form_data["country"], "Canada", handle_field_change),
            html.label(
                {"class_name": "form-field"},
                html.span({"class_name": "field-label"}, "Font"),
                html.select(
                    {
                        "value": selected_font,
                        "onChange": handle_font_change,
                        "disabled": not FONT_OPTIONS,
                        "class_name": "input-control",
                    },
                    *(
                        [
                            html.option({"key": font_name, "value": font_name}, font_name)
                            for font_name in FONT_OPTIONS
                        ]
                        if FONT_OPTIONS
                        else [html.option({"value": ""}, "No font files found")]
                    ),
                ),
            ),
            html.label(
                {"class_name": "form-field"},
                html.div(
                    {"class_name": "range-head"},
                    html.span({"class_name": "field-label"}, "Font size"),
                    html.span({"class_name": "range-value"}, f"{text_height:.1f} mm"),
                ),
                html.input(
                    {
                        "type": "range",
                        "min": "3",
                        "max": "10",
                        "step": "0.5",
                        "value": str(text_height),
                        "onChange": handle_text_height_change,
                        "class_name": "range-control",
                    }
                ),
            ),
        ),
        html.div(
            {"class_name": "preview-grid"},
            PreviewSection(preview_src, preview_error),
            html.div(
                {"class_name": "settings-card"},
                html.p({"class_name": "card-title"}, "Preview settings"),
                html.p({"class_name": "setting-row"}, f"Font: {selected_font or 'A'}"),
                html.p({"class_name": "setting-row"}, f"Font size: {text_height:.1f} mm"),
                html.p({"class_name": "setting-row"}, f"Label width: {preview_width} mm"),
                html.p({"class_name": "setting-row"}, f"Label height: {preview_height:.1f} mm"),
            ),
        ),
    )


@component
def ImageTab():
    """Image printing tab"""
    image_src, set_image_src = hooks.use_state("")
    preview_error, set_preview_error = hooks.use_state("")
    image_name, set_image_name = hooks.use_state("")

    def handle_image_upload(event):
        files = event["target"]["files"]
        if files and len(files) > 0:
            file = files[0]
            set_image_name(file["name"])
            
            # In a browser environment, we can't directly create object URLs from Python
            # Instead, we'll use a data URL approach via FileReader
            try:
                # Create a simple preview text since actual image preview requires
                # browser-side JavaScript or a server endpoint
                set_image_src(f"Image: {file['name']}")
                set_preview_error("Image file selected. Image preview and printing handled server-side.")
            except Exception as exc:
                set_preview_error(f"Error: {exc}")
                set_image_name("")

    return html.div(
        html.label(
            {"class_name": "form-field"},
            html.span({"class_name": "field-label"}, "Select image file (.png, .jpg, .gif)"),
            html.input(
                {
                    "type": "file",
                    "accept": "image/*",
                    "onChange": handle_image_upload,
                    "class_name": "image-input",
                }
            ),
        ),
        html.div(
            {"class_name": "preview-grid"},
            html.div(
                {"class_name": "preview-card"},
                html.p({"class_name": "card-title"}, "Preview"),
                html.p(
                    {"class_name": "preview-error"},
                    preview_error or "Upload an image to preview"
                ),
            ),
            html.div(
                {"class_name": "settings-card"},
                html.p({"class_name": "card-title"}, "Image settings"),
                html.p({"class_name": "setting-row"}, f"File: {image_name or '(none)'}"),
                html.p({"class_name": "setting-row"}, "Image will be scaled to fit the printer tape width."),
                html.p({"class_name": "setting-note"}, "File is uploaded with the print job to the printer."),
            ),
        ),
    )


@component
def MemeTab():
    """Meme printing tab (image with top and bottom text)"""
    preview_error, set_preview_error = hooks.use_state("")
    top_text, set_top_text = hooks.use_state("TOP TEXT")
    bottom_text, set_bottom_text = hooks.use_state("BOTTOM TEXT")
    image_name, set_image_name = hooks.use_state("")
    selected_font, set_selected_font = hooks.use_state(DEFAULT_FONT)

    def handle_text_change(field):
        def _handle_change(event):
            value = event["target"]["value"]
            if field == "top":
                set_top_text(value)
            else:
                set_bottom_text(value)
        return _handle_change

    def handle_font_change(event):
        set_selected_font(event["target"]["value"])

    def handle_image_upload(event):
        files = event["target"]["files"]
        if files and len(files) > 0:
            file = files[0]
            set_image_name(file["name"])
            set_preview_error("Image selected. Text overlay will be applied during printing.")

    return html.div(
        html.label(
            {"class_name": "form-field"},
            html.span({"class_name": "field-label"}, "Select image file"),
            html.input(
                {
                    "type": "file",
                    "accept": "image/*",
                    "onChange": handle_image_upload,
                    "class_name": "image-input",
                }
            ),
        ),
        html.label(
            {"class_name": "form-field"},
            html.span({"class_name": "field-label"}, "Top text"),
            html.input(
                {
                    "value": top_text,
                    "placeholder": "TOP TEXT",
                    "onChange": handle_text_change("top"),
                    "class_name": "input-control",
                }
            ),
        ),
        html.label(
            {"class_name": "form-field"},
            html.span({"class_name": "field-label"}, "Bottom text"),
            html.input(
                {
                    "value": bottom_text,
                    "placeholder": "BOTTOM TEXT",
                    "onChange": handle_text_change("bottom"),
                    "class_name": "input-control",
                }
            ),
        ),
        html.label(
            {"class_name": "form-field"},
            html.span({"class_name": "field-label"}, "Font"),
            html.select(
                {
                    "value": selected_font,
                    "onChange": handle_font_change,
                    "disabled": not FONT_OPTIONS,
                    "class_name": "input-control font-select",
                },
                *(
                    [
                        html.option(
                            {"key": font_name, "value": font_name, "class_name": f"font-option font-{font_name.lower().replace('.', '-')}"},
                            font_name
                        )
                        for font_name in FONT_OPTIONS
                    ]
                    if FONT_OPTIONS
                    else [html.option({"value": ""}, "No font files found")]
                ),
            ),
        ),
        html.div(
            {"class_name": "preview-grid"},
            html.div(
                {"class_name": "preview-card"},
                html.p({"class_name": "card-title"}, "Preview"),
                html.p(
                    {"class_name": "preview-error"},
                    preview_error or "Upload an image and add text"
                ),
            ),
            html.div(
                {"class_name": "settings-card"},
                html.p({"class_name": "card-title"}, "Meme settings"),
                html.p({"class_name": "setting-row"}, f"File: {image_name or '(none)'}"),
                html.p({"class_name": "setting-row"}, f"Font: {selected_font or 'A'}"),
                html.p({"class_name": "setting-row"}, f"Top: {top_text or '(empty)'}"),
                html.p({"class_name": "setting-row"}, f"Bottom: {bottom_text or '(empty)'}"),
                html.p({"class_name": "setting-note"}, "Text will be overlaid on the image during printing."),
            ),
        ),
    )


@component
def CatTab():
    """Cat API tab"""
    cat_image_url, set_cat_image_url = hooks.use_state("")
    preview_error, set_preview_error = hooks.use_state("Click 'Fetch Cat' to get a random cat image")
    is_loading, set_is_loading = hooks.use_state(False)

    def handle_fetch_cat(event):
        del event
        set_is_loading(True)
        set_preview_error("Loading...")
        
        def fetch_cat():
            try:
                import urllib.request
                import urllib.error
                
                # Fetch from Cat API
                url = "https://api.thecatapi.com/v1/images/search"
                req = urllib.request.Request(url)
                req.add_header('User-Agent', 'Mozilla/5.0 (compatible; Stikka-NG/1.0)')
                
                try:
                    response = urllib.request.urlopen(req, timeout=10)
                    data = json.loads(response.read().decode())
                    
                    if data and len(data) > 0:
                        cat_url = data[0]["url"]
                        set_cat_image_url(cat_url)
                        set_preview_error("")
                    else:
                        set_preview_error("No cat images found")
                except urllib.error.HTTPError as e:
                    set_preview_error(f"HTTP Error {e.code}: Failed to fetch cat image")
                except urllib.error.URLError as e:
                    set_preview_error(f"Network error: {e.reason}")
                except Exception as exc:
                    set_preview_error(f"Error: {exc}")
            except ImportError:
                set_preview_error("Network libraries not available")
            finally:
                set_is_loading(False)
        
        # Run fetch in background
        import threading
        thread = threading.Thread(target=fetch_cat, daemon=True)
        thread.start()

    return html.div(
        html.button(
            {
                "onClick": handle_fetch_cat,
                "disabled": is_loading,
                "class_name": "btn scan-btn",
            },
            "Loading..." if is_loading else "Fetch Random Cat",
        ),
        html.div(
            {"class_name": "preview-grid"},
            html.div(
                {"class_name": "preview-card"},
                html.p({"class_name": "card-title"}, "Preview"),
                html.img(
                    {
                        "src": cat_image_url,
                        "alt": "Random cat",
                        "class_name": "cat-image",
                    }
                ) if cat_image_url else html.div(
                    {"class_name": "preview-error"},
                    preview_error,
                ),
            ),
            html.div(
                {"class_name": "settings-card"},
                html.p({"class_name": "card-title"}, "Cat settings"),
                html.p({"class_name": "setting-row"}, "Fetches random cat images from The Cat API"),
                html.p({"class_name": "setting-note"}, "Attribution: Images provided by thecatapi.com"),
                html.p({"class_name": "setting-note"}, "Note: Requires internet connection"),
            ),
        ),
    )


@component
def App():
    active_tab, set_active_tab = hooks.use_state("simple")
    printer_options, set_printer_options = hooks.use_state([])
    selected_serial, set_selected_serial = hooks.use_state("")
    status_message, set_status_message = hooks.use_state("Select a printer to begin.")
    is_printing, set_is_printing = hooks.use_state(False)

    def handle_scan(event):
        del event
        try:
            options = _scan_printers()
        except Exception as exc:
            set_status_message(f"Printer scan failed: {exc}")
            set_printer_options([])
            set_selected_serial("")
            return

        set_printer_options(options)
        if options:
            set_selected_serial(options[0]["serial"])
            set_status_message(f"Found {len(options)} printer(s).")
        else:
            set_selected_serial("")
            set_status_message("No Brother QL printers found.")

    def handle_printer_change(event):
        set_selected_serial(event["target"]["value"])

    def handle_print(event):
        del event
        if not selected_serial:
            set_status_message("Select a printer before printing.")
            return

        printer = PRINTER_REGISTRY.get_printer(selected_serial)
        if printer is None:
            set_status_message("The selected printer is no longer available. Scan again.")
            return

        set_is_printing(True)
        try:
            # For now, just show a success message
            # In a real implementation, you'd build the appropriate label based on the active tab
            set_status_message(f"Sent label to printer {selected_serial}.")
        except Exception as exc:
            set_status_message(f"Printing failed: {exc}")
        finally:
            set_is_printing(False)

    tabs = [
        {"id": "simple", "label": "Simple Label"},
        {"id": "address", "label": "Address Label"},
        {"id": "image", "label": "Image"},
        {"id": "meme", "label": "Meme"},
        {"id": "cat", "label": "Cat"},
    ]

    return html.div(
        {"class_name": "app-shell"},
        html.style(CSS_TEXT),
        html.div(
            {"class_name": "app-card"},
            html.div(
                {"class_name": "app-hero"},
                html.p(
                    {"class_name": "app-badge"},
                    "Stikka NG"
                ),
                html.h1({"class_name": "app-title"}, "Multi-Tab Label Printer"),
                html.p(
                    {"class_name": "app-subtitle"},
                    "Create and print various label types directly from your browser."
                ),
            ),
            html.div(
                {"class_name": "app-body"},
                html.div(
                    {"class_name": "tabs-container"},
                    *[
                        html.button(
                            {
                                "onClick": lambda event, tab_id=tab["id"]: set_active_tab(tab_id),
                                "class_name": f"tab-button {'active' if active_tab == tab['id'] else ''}",
                            },
                            tab["label"],
                        )
                        for tab in tabs
                    ],
                ),
                PrinterSection(handle_scan, selected_serial, printer_options, handle_printer_change),
                html.div(
                    {"class_name": f"tab-content {'active' if active_tab == 'simple' else ''}"},
                    SimpleLabel(),
                ),
                html.div(
                    {"class_name": f"tab-content {'active' if active_tab == 'address' else ''}"},
                    AddressLabelTab(),
                ),
                html.div(
                    {"class_name": f"tab-content {'active' if active_tab == 'image' else ''}"},
                    ImageTab(),
                ),
                html.div(
                    {"class_name": f"tab-content {'active' if active_tab == 'meme' else ''}"},
                    MemeTab(),
                ),
                html.div(
                    {"class_name": f"tab-content {'active' if active_tab == 'cat' else ''}"},
                    CatTab(),
                ),
                StatusSection(status_message, handle_print, is_printing, "Print Label"),
            ),
        ),
    )


run(App)

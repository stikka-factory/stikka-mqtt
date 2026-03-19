import base64
from io import BytesIO
from pathlib import Path

from reactpy import component, html, hooks, run

from label import StikkaLabel
from printer_ql import BrotherPrintJob, BrotherPrinter


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
DEFAULT_FONT = "Orbitron Black.otf" if "Orbitron Black.otf" in FONT_OPTIONS else (FONT_OPTIONS[0] if FONT_OPTIONS else "")
DEFAULT_TEXT_HEIGHT = 5.0
PRINTERS = {}
DEFAULT_FORM = {
    "name": "",
    "street": "",
    "zip_code": "",
    "city": "",
    "country": "",
}


def _scan_printers():
    global PRINTERS
    PRINTERS = BrotherPrinter.find("pyusb")
    return [
        {
            "serial": serial,
            "model": printer.model,
            "media": printer.status.media_name,
        }
        for serial, printer in PRINTERS.items()
    ]


def _build_label(form_data, font_name, width, text_height):
    font_value = str(FONT_DIR / font_name) if font_name else "A"
    return StikkaLabel.address_label(
        width=width,
        name=form_data["name"].strip() or "Jane Smith",
        street=form_data["street"].strip() or "456 Elm St",
        zip_code=form_data["zip_code"].strip() or "67890",
        city=form_data["city"].strip() or "Othertown",
        country=form_data["country"].strip() or "Canada",
        font=font_value,
        text_height=text_height,
    )


def _render_preview_src(form_data, font_name, width, text_height):
    buffer = BytesIO()
    preview_image = _build_label(form_data, font_name, width, text_height).render_image(framing=True)
    preview_image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _make_field(label_text, field_name, value, placeholder, on_change):
    return html.label(
        {"class_name": "form-field"},
        html.span({"class_name": "field-label"}, label_text),
        html.input(
            {
                "value": value,
                "placeholder": placeholder,
                "onChange": on_change(field_name),
                "class_name": "input-control",
            }
        ),
    )


@component
def App():
    printer_options, set_printer_options = hooks.use_state([])
    selected_serial, set_selected_serial = hooks.use_state("")
    form_data, set_form_data = hooks.use_state(DEFAULT_FORM)
    selected_font, set_selected_font = hooks.use_state(DEFAULT_FONT)
    text_height, set_text_height = hooks.use_state(DEFAULT_TEXT_HEIGHT)
    status_message, set_status_message = hooks.use_state("Scan for connected Brother QL printers to begin.")
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
            set_status_message("No Brother QL printers found on the pyusb backend.")

    def handle_field_change(field_name):
        def _handle_change(event):
            value = event["target"]["value"]
            set_form_data(lambda prev: {**prev, field_name: value})

        return _handle_change

    def handle_printer_change(event):
        set_selected_serial(event["target"]["value"])

    def handle_font_change(event):
        set_selected_font(event["target"]["value"])

    def handle_text_height_change(event):
        set_text_height(float(event["target"]["value"]))

    def handle_print(event):
        del event
        missing_fields = [
            label
            for key, label in (
                ("name", "name"),
                ("street", "street"),
                ("zip_code", "zip code"),
                ("city", "city"),
                ("country", "country"),
            )
            if not form_data[key].strip()
        ]

        if not selected_serial:
            set_status_message("Select a printer before printing.")
            return

        if missing_fields:
            set_status_message("Missing required fields: " + ", ".join(missing_fields))
            return

        printer = PRINTERS.get(selected_serial)
        if printer is None:
            set_status_message("The selected printer is no longer available. Scan again.")
            return

        set_is_printing(True)
        try:
            label = _build_label(form_data, selected_font, printer.status.media_width, text_height)
            image = label.render_image()
            printer.print_job(BrotherPrintJob(image))
            set_status_message(f"Sent address label to printer {selected_serial}.")
        except Exception as exc:
            set_status_message(f"Printing failed: {exc}")
        finally:
            set_is_printing(False)

    preview_width = 62
    if selected_serial and selected_serial in PRINTERS:
        preview_width = PRINTERS[selected_serial].status.media_width
    preview_height = text_height + (4 * text_height) + (3 * 2) + text_height  # top + 4 lines + 3 gaps + bottom
    preview_src = ""
    preview_error = ""
    try:
        preview_src = _render_preview_src(form_data, selected_font, preview_width, text_height)
    except Exception as exc:
        preview_error = f"Preview unavailable: {exc}"

    print_btn_classes = "btn print-btn"
    if is_printing:
        print_btn_classes += " is-disabled"

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
                html.h1({"class_name": "app-title"}, "Address Label Printer"),
                html.p(
                    {"class_name": "app-subtitle"},
                    "Select a connected Brother QL printer, enter the recipient data, and send a single address label directly from the browser."
                ),
            ),
            html.div(
                {"class_name": "app-body"},
                html.div(
                    {"class_name": "toolbar"},
                    html.label(
                        {"class_name": "form-field printer-field"},
                        html.span({"class_name": "field-label"}, "Printer"),
                        html.select(
                            {
                                "value": selected_serial,
                                "onChange": handle_printer_change,
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
                            "onClick": handle_scan,
                            "class_name": "btn scan-btn",
                        },
                        "Scan printers",
                    ),
                ),
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
                    html.div(
                        {"class_name": "preview-card"},
                        html.p(
                            {"class_name": "card-title"},
                            "Preview"
                        ),
                        html.img(
                            {
                                "src": preview_src,
                                "alt": "Address label preview",
                                "class_name": "preview-image",
                            }
                        ) if preview_src else html.div(
                            {"class_name": "preview-error"},
                            preview_error or "Preview unavailable."
                        ),
                    ),
                    html.div(
                        {"class_name": "settings-card"},
                        html.p({"class_name": "card-title"}, "Preview settings"),
                        html.p({"class_name": "setting-row"}, f"Font: {selected_font or 'A'}"),
                        html.p({"class_name": "setting-row"}, f"Font size: {text_height:.1f} mm"),
                        html.p({"class_name": "setting-row"}, f"Label width: {preview_width} mm"),
                        html.p({"class_name": "setting-row"}, f"Label height: {preview_height:.1f} mm"),
                        html.p(
                            {"class_name": "setting-note"},
                            "The preview updates as you type. The label height grows with the selected font size. If no printer is selected yet, it uses a 62 mm label width."
                        ),
                    ),
                ),
                html.div(
                    {"class_name": "status-row"},
                    html.div(
                        html.strong({"class_name": "status-title"}, "Status"),
                        html.p({"class_name": "status-message"}, status_message),
                    ),
                    html.button(
                        {
                            "onClick": handle_print,
                            "disabled": is_printing,
                            "class_name": print_btn_classes,
                        },
                        "Printing..." if is_printing else "Print address label",
                    ),
                ),
            ),
        ),
    )


run(App)

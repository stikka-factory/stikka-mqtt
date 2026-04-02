from io import BytesIO
import json
import os
from pathlib import Path
import sys
import traceback
from PIL import Image

# Ensure project root is on path when this file is run directly
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from reactpy import component, html, hooks, run

from label.label import StikkaLabel
from labelprinter.printer_ql import BrotherPrintJob
from labelprinter.printer_zpl import ZPLPrintJob, ZPLPrinter
from webui.stikka_factory.tabs.tab_config import ConfigTab
from webui.stikka_factory.tabs.tab_media import MediaTab
from webui.stikka_factory.tabs.webui_common import (
    CSS_TEXT,
    DEFAULT_FONT,
    PRINTER_REGISTRY,
    PrinterSection,
    StatusSection,
    draw_overlay_text,
    image_from_uploaded_payload,
    get_printer_dpi,
    get_printer_label_length_mm,
    get_printer_label_width_mm,
    get_printer_printable_width_px,
    format_preview_to_media,
    process_image_for_label,
    scan_printers,
)
import logger as _logger

log = _logger.log

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = PROJECT_ROOT / "printers_config.json"
CONFIG_TAB_PASSWORD = os.environ.get("STIKKA_CONFIG_PASSWORD", "stikka")


def _load_config_text():
    try:
        return CONFIG_FILE.read_text(encoding="utf-8")
    except OSError:
        return '{\n  "printers": []\n}\n'


@component
def App():
    active_tab, set_active_tab = hooks.use_state("simple")
    printer_options, set_printer_options = hooks.use_state([])
    selected_serial, set_selected_serial = hooks.use_state("")
    status_message, set_status_message = hooks.use_state("Select a printer to begin.")
    is_printing, set_is_printing = hooks.use_state(False)

    # Unified media tab state
    media_url, set_media_url = hooks.use_state("")
    media_uploaded_payload, set_media_uploaded_payload = hooks.use_state("")
    media_use_white_background, set_media_use_white_background = hooks.use_state(False)
    media_overlay_text, set_media_overlay_text = hooks.use_state("")
    media_text_black, set_media_text_black = hooks.use_state(False)
    media_text_align, set_media_text_align = hooks.use_state("center")
    media_text_vertical_align, set_media_text_vertical_align = hooks.use_state("center")
    media_text_rotate_90, set_media_text_rotate_90 = hooks.use_state(False)
    media_text_offset_x, set_media_text_offset_x = hooks.use_state(0)
    media_text_offset_y, set_media_text_offset_y = hooks.use_state(0)
    media_image_offset_x, set_media_image_offset_x = hooks.use_state(0)
    media_image_offset_y, set_media_image_offset_y = hooks.use_state(0)
    media_crop_to_center, set_media_crop_to_center = hooks.use_state(False)
    media_rotate_image, set_media_rotate_image = hooks.use_state(False)
    media_font, set_media_font = hooks.use_state(DEFAULT_FONT)
    media_text_size, set_media_text_size = hooks.use_state(36)
    media_black_point, set_media_black_point = hooks.use_state(32)
    media_white_point, set_media_white_point = hooks.use_state(224)
    media_contrast, set_media_contrast = hooks.use_state(1.2)

    # Config tab state
    config_password_input, set_config_password_input = hooks.use_state("")
    config_unlocked, set_config_unlocked = hooks.use_state(False)
    config_text, set_config_text = hooks.use_state(_load_config_text())

    def reload_printers_runtime():
        # Clear the registry and reload all printers from config
        PRINTER_REGISTRY.clear_all()
        options = scan_printers()
        set_printer_options(options)
        if options:
            serials = {option["serial"] for option in options}
            if selected_serial not in serials:
                set_selected_serial(options[0]["serial"])
            return len(options)
        set_selected_serial("")
        return 0

    def handle_scan(event):
        del event
        try:
            options = scan_printers()
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
            set_status_message("No printers found.")

    def handle_printer_change(event):
        set_selected_serial(event["target"]["value"])

    def handle_config_password_change(event):
        set_config_password_input(event["target"]["value"])

    def handle_unlock_config(event):
        del event
        if config_password_input == CONFIG_TAB_PASSWORD:
            set_config_unlocked(True)
            set_status_message("Config tab unlocked.")
        else:
            set_status_message("Invalid config password.")

    def handle_reload_config_from_disk(event):
        del event
        set_config_text(_load_config_text())
        set_status_message("Reloaded printers_config.json from disk.")

    def handle_config_text_change(event):
        set_config_text(event["target"]["value"])

    def handle_save_config(event):
        del event
        if not config_unlocked:
            set_status_message("Unlock the config tab before saving.")
            return

        try:
            parsed = json.loads(config_text)
            normalized = json.dumps(parsed, indent=2) + "\n"
            CONFIG_FILE.write_text(normalized, encoding="utf-8")
            set_config_text(normalized)
            count = reload_printers_runtime()
            set_status_message(f"Saved printers_config.json and reloaded {count} printer(s).")
        except json.JSONDecodeError as exc:
            set_status_message(f"Invalid JSON: line {exc.lineno}, column {exc.colno}: {exc.msg}")
        except Exception as exc:
            set_status_message(f"Failed to save config: {exc}")

    def handle_reload_printers(event):
        del event
        try:
            count = reload_printers_runtime()
            set_status_message(f"Reloaded printer configuration. Found {count} printer(s).")
        except Exception as exc:
            set_status_message(f"Reload failed: {exc}")

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

        def do_print():
            try:
                label = None
                label_width_mm = get_printer_label_width_mm(printer)
                label_length_mm = get_printer_label_length_mm(printer)
                label_dpi = get_printer_dpi(printer)
                tape_width_px = get_printer_printable_width_px(printer)
                tape_length_px = (
                    int(round((label_length_mm / label_width_mm) * tape_width_px))
                    if label_length_mm and label_width_mm > 0
                    else None
                )
                if active_tab == "simple":
                    if media_uploaded_payload:
                        img = image_from_uploaded_payload(media_uploaded_payload)
                    elif media_url.strip():
                        import urllib.request
                        req = urllib.request.Request(media_url.strip())
                        req.add_header('User-Agent', 'Mozilla/5.0 (compatible; Stikka-NG/1.0)')
                        with urllib.request.urlopen(req, timeout=10) as response:
                            img_data = response.read()
                        img = Image.open(BytesIO(img_data)).convert("RGB")
                    elif media_use_white_background:
                        blank_width = max(1, int(tape_width_px))
                        blank_height = max(1, int(tape_length_px)) if tape_length_px else blank_width
                        img = Image.new("RGB", (blank_width, blank_height), "white")
                    else:
                        set_status_message("Set an image URL, upload an image, or use white background before printing.")
                        set_is_printing(False)
                        return

                    img = process_image_for_label(
                        img,
                        black_point=media_black_point,
                        white_point=media_white_point,
                        contrast=media_contrast,
                        label_width=tape_width_px,
                    )
                    img = format_preview_to_media(
                        img,
                        label_width_px=tape_width_px,
                        label_length_px=tape_length_px,
                        rotate=media_rotate_image,
                        crop_to_center=media_crop_to_center,
                        image_offset_x=media_image_offset_x,
                        image_offset_y=media_image_offset_y,
                    )
                    draw_overlay_text(
                        img,
                        overlay_text=media_overlay_text,
                        selected_font=media_font,
                        text_size=media_text_size,
                        text_black=media_text_black,
                        align=media_text_align,
                        vertical_align=media_text_vertical_align,
                        offset_x=media_text_offset_x,
                        offset_y=media_text_offset_y,
                        rotate_90=media_text_rotate_90,
                    )
                    label_height_mm = label_length_mm if label_length_mm else img.height / (tape_width_px / label_width_mm)
                    label = StikkaLabel(label_width_mm, label_height_mm, dpi=label_dpi)
                    label.add_image(img, x=0, y=0, width=label_width_mm, height=label_height_mm)

                if label is not None:
                    if isinstance(printer, ZPLPrinter):
                        job = ZPLPrintJob(label=label)
                        result = printer.add_to_queue(job)
                        if isinstance(result, dict) and result.get("ok"):
                            set_status_message(
                                f"Sent {result.get('bytes', 0)} bytes to ZPL printer {selected_serial} ({result.get('endpoint', 'unknown endpoint')})."
                            )
                        else:
                            set_status_message(f"Sent label to printer {selected_serial}.")
                    else:
                        job = BrotherPrintJob(label=label)
                        printer.add_to_queue(job)
                        set_status_message(f"Queued label for printer {selected_serial}.")
                else:
                    set_status_message("Printing is not supported for this tab yet.")
            except Exception as exc:
                tb = traceback.format_exc()
                log.error(f"Printing failed with traceback:\n{tb}")
                tb_tail = "\n".join(tb.strip().splitlines()[-8:])
                set_status_message(f"Printing failed: {exc}\n{tb_tail}")
            finally:
                set_is_printing(False)

        import threading
        threading.Thread(target=do_print, daemon=True).start()

    tabs = [
        {"id": "simple", "label": "Label"},
        {"id": "config", "label": "Config"},
    ]

    def _on_tab_click(tab_id):
        def _handler(event):
            del event
            set_active_tab(tab_id)

        return _handler

    selected_printer = PRINTER_REGISTRY.get_printer(selected_serial) if selected_serial else None
    preview_width_px = get_printer_printable_width_px(selected_printer) if selected_printer else 696
    preview_width_mm = get_printer_label_width_mm(selected_printer) if selected_printer else 62
    preview_length_mm = get_printer_label_length_mm(selected_printer)
    preview_length_px = (
        int(round((preview_length_mm / preview_width_mm) * preview_width_px))
        if preview_length_mm and preview_width_mm > 0
        else None
    )

    return html.div(
        {"class_name": "app-shell"},
        html.style(CSS_TEXT),
        html.div(
            {"class_name": "app-card"},
            html.div(
                {"class_name": "app-hero"},
                # html.p(
                #     {"class_name": "app-badge"},
                #     "Stikka NG"
                # ),
                html.h1({"class_name": "app-title"}, "✨ Stikka Factory ✨"),
                html.p(
                    {"class_name": "app-subtitle"},
                    "Kleben und kleben lassen."
                ),
            ),
            html.div(
                {"class_name": "app-body"},
                html.div(
                    {"class_name": "tabs-container"},
                    *[
                        html.button(
                            {
                                "onClick": _on_tab_click(tab["id"]),
                                "class_name": f"tab-button {'active' if active_tab == tab['id'] else ''}",
                                "key": tab["id"],
                            },
                            tab["label"],
                        )
                        for tab in tabs
                    ],
                ),
                PrinterSection(handle_scan, selected_serial, printer_options, handle_printer_change)
                if active_tab != "config"
                else None,
                html.div(
                    {
                        "class_name": "tab-content stable-tab-panel",
                        "key": "simple-panel",
                        "style": {"display": "block" if active_tab == "simple" else "none"},
                    },
                    MediaTab(
                        media_url,
                        set_media_url,
                        media_uploaded_payload,
                        set_media_uploaded_payload,
                        media_use_white_background,
                        set_media_use_white_background,
                        media_overlay_text,
                        set_media_overlay_text,
                        media_text_black,
                        set_media_text_black,
                        media_text_align,
                        set_media_text_align,
                        media_crop_to_center,
                        set_media_crop_to_center,
                        media_rotate_image,
                        set_media_rotate_image,
                        media_image_offset_x,
                        set_media_image_offset_x,
                        media_image_offset_y,
                        set_media_image_offset_y,
                        media_text_vertical_align,
                        set_media_text_vertical_align,
                        media_text_rotate_90,
                        set_media_text_rotate_90,
                        media_text_offset_x,
                        set_media_text_offset_x,
                        media_text_offset_y,
                        set_media_text_offset_y,
                        media_font,
                        set_media_font,
                        media_text_size,
                        set_media_text_size,
                        media_black_point,
                        set_media_black_point,
                        media_white_point,
                        set_media_white_point,
                        media_contrast,
                        set_media_contrast,
                        preview_width_px,
                        preview_length_px,
                    ),
                ),
                html.div(
                    {
                        "class_name": "tab-content stable-tab-panel",
                        "key": "config-panel",
                        "style": {"display": "block" if active_tab == "config" else "none"},
                    },
                    ConfigTab(
                        config_password_input,
                        handle_config_password_change,
                        handle_unlock_config,
                        handle_reload_config_from_disk,
                        handle_save_config,
                        handle_reload_printers,
                        config_text,
                        handle_config_text_change,
                        config_unlocked,
                    ),
                ),
                StatusSection(status_message, handle_print, is_printing, "Print Label")
                if active_tab != "config"
                else html.div(
                    {"class_name": "status-row"},
                    html.div(
                        html.strong({"class_name": "status-title"}, "Config status"),
                        html.p({"class_name": "status-message"}, status_message),
                    ),
                ),
            ),
        ),
    )


# Custom backend setup to include the file upload endpoint
run(App)

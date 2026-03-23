from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

from reactpy import component, html, hooks, run

from label import StikkaLabel
from printer_ql import BrotherPrintJob
from tab_address import AddressLabelTab
from tab_cat import CatTab
from tab_image import ImageTab
from tab_meme import MemeTab
from tab_simple import SimpleLabel
from webui_common import (
    CSS_TEXT,
    DEFAULT_FONT,
    DEFAULT_FORM,
    FONT_DIR,
    PRINTER_REGISTRY,
    PrinterSection,
    StatusSection,
    get_printer_label_width_mm,
    get_printer_printable_width_px,
    process_image_for_label,
    scan_printers,
)


@component
def App():
    active_tab, set_active_tab = hooks.use_state("simple")
    printer_options, set_printer_options = hooks.use_state([])
    selected_serial, set_selected_serial = hooks.use_state("")
    status_message, set_status_message = hooks.use_state("Select a printer to begin.")
    is_printing, set_is_printing = hooks.use_state(False)

    # Simple label state
    simple_text, set_simple_text = hooks.use_state("Hello\nWorld")
    simple_height, set_simple_height = hooks.use_state(5.0)
    simple_font, set_simple_font = hooks.use_state(DEFAULT_FONT)

    # Address label state
    address_form, set_address_form = hooks.use_state(DEFAULT_FORM)
    address_height, set_address_height = hooks.use_state(5.0)
    address_font, set_address_font = hooks.use_state(DEFAULT_FONT)

    # Cat tab state
    cat_url, set_cat_url = hooks.use_state("")

    # Image tab state
    image_url, set_image_url = hooks.use_state("")
    image_black_point, set_image_black_point = hooks.use_state(32)
    image_white_point, set_image_white_point = hooks.use_state(224)
    image_contrast, set_image_contrast = hooks.use_state(1.2)

    # Meme tab state
    meme_url, set_meme_url = hooks.use_state("")
    meme_top_text, set_meme_top_text = hooks.use_state("TOP TEXT")
    meme_bottom_text, set_meme_bottom_text = hooks.use_state("BOTTOM TEXT")
    meme_font, set_meme_font = hooks.use_state(DEFAULT_FONT)
    meme_black_point, set_meme_black_point = hooks.use_state(32)
    meme_white_point, set_meme_white_point = hooks.use_state(224)
    meme_contrast, set_meme_contrast = hooks.use_state(1.2)

    # Cat tab image processing state
    cat_black_point, set_cat_black_point = hooks.use_state(32)
    cat_white_point, set_cat_white_point = hooks.use_state(224)
    cat_contrast, set_cat_contrast = hooks.use_state(1.2)

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

        def do_print():
            try:
                label = None
                label_width_mm = get_printer_label_width_mm(printer)
                tape_width_px = get_printer_printable_width_px(printer)
                if active_tab == "simple":
                    lines = simple_text.strip().split('\n') if simple_text.strip() else [""]
                    num_lines = len(lines)
                    line_spacing = 2
                    label_height = simple_height + (num_lines * simple_height) + ((num_lines - 1) * line_spacing) + simple_height
                    label = StikkaLabel(label_width_mm, label_height)
                    font_path = str(FONT_DIR / simple_font) if simple_font else "A"
                    y_pos = simple_height
                    for line in lines:
                        label.add_text(
                            line.strip() or " ",
                            x=5,
                            y=y_pos,
                            char_height=simple_height,
                            char_width=1.0,
                            line_width=int(label_width_mm - 10),
                            font=font_path,
                        )
                        y_pos += simple_height + line_spacing
                elif active_tab == "address":
                    font_path = str(FONT_DIR / address_font) if address_font else "A"
                    label = StikkaLabel.address_label(
                        width=label_width_mm,
                        name=address_form["name"].strip() or "Jane Smith",
                        street=address_form["street"].strip() or "456 Elm St",
                        zip_code=address_form["zip_code"].strip() or "67890",
                        city=address_form["city"].strip() or "Othertown",
                        country=address_form["country"].strip() or "",
                        font=font_path,
                        text_height=address_height,
                    )

                elif active_tab == "cat":
                    if not cat_url:
                        set_status_message("No cat image fetched yet.")
                        set_is_printing(False)
                        return
                    import urllib.request
                    req = urllib.request.Request(cat_url)
                    req.add_header('User-Agent', 'Mozilla/5.0 (compatible; Stikka-NG/1.0)')
                    with urllib.request.urlopen(req, timeout=10) as response:
                        img_data = response.read()
                    img = Image.open(BytesIO(img_data)).convert("RGB")

                    img = process_image_for_label(
                        img,
                        black_point=cat_black_point,
                        white_point=cat_white_point,
                        contrast=cat_contrast,
                        label_width=tape_width_px,
                    )
                    label_height_mm = img.height / (tape_width_px / label_width_mm)
                    label = StikkaLabel(label_width_mm, label_height_mm)
                    label.add_image(img, x=0, y=0, width=label_width_mm, height=label_height_mm)

                elif active_tab == "image":
                    if not image_url.strip():
                        set_status_message("Set an image URL in the Image tab before printing.")
                        set_is_printing(False)
                        return
                    import urllib.request
                    req = urllib.request.Request(image_url.strip())
                    req.add_header('User-Agent', 'Mozilla/5.0 (compatible; Stikka-NG/1.0)')
                    with urllib.request.urlopen(req, timeout=10) as response:
                        img_data = response.read()
                    img = Image.open(BytesIO(img_data)).convert("RGB")
                    img = process_image_for_label(
                        img,
                        black_point=image_black_point,
                        white_point=image_white_point,
                        contrast=image_contrast,
                        label_width=tape_width_px,
                    )
                    label_height_mm = img.height / (tape_width_px / label_width_mm)
                    label = StikkaLabel(label_width_mm, label_height_mm)
                    label.add_image(img, x=0, y=0, width=label_width_mm, height=label_height_mm)
                elif active_tab == "meme":
                    if not meme_url.strip():
                        set_status_message("Set an image URL in the Meme tab before printing.")
                        set_is_printing(False)
                        return
                    import urllib.request
                    req = urllib.request.Request(meme_url.strip())
                    req.add_header('User-Agent', 'Mozilla/5.0 (compatible; Stikka-NG/1.0)')
                    with urllib.request.urlopen(req, timeout=10) as response:
                        img_data = response.read()
                    img = Image.open(BytesIO(img_data)).convert("RGB")
                    img = process_image_for_label(
                        img,
                        black_point=meme_black_point,
                        white_point=meme_white_point,
                        contrast=meme_contrast,
                        label_width=tape_width_px,
                    )

                    draw = ImageDraw.Draw(img)
                    try:
                        font_path = str(FONT_DIR / meme_font) if meme_font else None
                        font = ImageFont.truetype(font_path, size=max(18, img.width // 12)) if font_path else ImageFont.load_default()
                    except Exception:
                        font = ImageFont.load_default()

                    if meme_top_text.strip():
                        draw.text((10, 10), meme_top_text.strip(), fill="black", font=font)
                    if meme_bottom_text.strip():
                        text_bbox = draw.textbbox((0, 0), meme_bottom_text.strip(), font=font)
                        text_w = text_bbox[2] - text_bbox[0]
                        text_h = text_bbox[3] - text_bbox[1]
                        draw.text((max(10, (img.width - text_w) // 2), max(10, img.height - text_h - 10)), meme_bottom_text.strip(), fill="black", font=font)

                    label_height_mm = img.height / (tape_width_px / label_width_mm)
                    label = StikkaLabel(label_width_mm, label_height_mm)
                    label.add_image(img, x=0, y=0, width=label_width_mm, height=label_height_mm)

                if label is not None:
                    job = BrotherPrintJob(label=label)
                    printer.add_to_queue(job)
                    set_status_message(f"Sent label to printer {selected_serial}.")
                else:
                    set_status_message("Printing is not supported for this tab yet.")
            except Exception as exc:
                set_status_message(f"Printing failed: {exc}")
            finally:
                set_is_printing(False)

        import threading
        threading.Thread(target=do_print, daemon=True).start()

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
                    SimpleLabel(simple_text, set_simple_text, simple_height, set_simple_height, simple_font, set_simple_font),
                ),
                html.div(
                    {"class_name": f"tab-content {'active' if active_tab == 'address' else ''}"},
                    AddressLabelTab(address_form, set_address_form, address_height, set_address_height, address_font, set_address_font),
                ),
                html.div(
                    {"class_name": f"tab-content {'active' if active_tab == 'image' else ''}"},
                    ImageTab(
                        image_url,
                        set_image_url,
                        image_black_point,
                        set_image_black_point,
                        image_white_point,
                        set_image_white_point,
                        image_contrast,
                        set_image_contrast,
                    ),
                ),
                html.div(
                    {"class_name": f"tab-content {'active' if active_tab == 'meme' else ''}"},
                    MemeTab(
                        meme_url,
                        set_meme_url,
                        meme_top_text,
                        set_meme_top_text,
                        meme_bottom_text,
                        set_meme_bottom_text,
                        meme_font,
                        set_meme_font,
                        meme_black_point,
                        set_meme_black_point,
                        meme_white_point,
                        set_meme_white_point,
                        meme_contrast,
                        set_meme_contrast,
                    ),
                ),
                html.div(
                    {"class_name": f"tab-content {'active' if active_tab == 'cat' else ''}"},
                    CatTab(
                        cat_url,
                        set_cat_url,
                        cat_black_point,
                        set_cat_black_point,
                        cat_white_point,
                        set_cat_white_point,
                        cat_contrast,
                        set_cat_contrast,
                    ),
                ),
                StatusSection(status_message, handle_print, is_printing, "Print Label"),
            ),
        ),
    )


run(App)

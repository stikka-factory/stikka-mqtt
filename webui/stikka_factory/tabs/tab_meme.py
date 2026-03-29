from PIL import ImageDraw, ImageFont
from reactpy import component, html, hooks

from .webui_common import (
    FONT_DIR,
    FONT_OPTIONS,
    ImageAdjustControls,
    fetch_image_from_url,
    format_preview_to_media,
    process_image_for_label,
    render_preview_src,
)


@component
def MemeTab(
    image_url,
    set_image_url,
    top_text,
    set_top_text,
    bottom_text,
    set_bottom_text,
    selected_font,
    set_selected_font,
    black_point,
    set_black_point,
    white_point,
    set_white_point,
    contrast,
    set_contrast,
    preview_width_px=None,
    preview_length_px=None,
):
    preview_error, set_preview_error = hooks.use_state("")
    image_name, set_image_name = hooks.use_state("")

    def handle_url_change(event):
        set_image_url(event["target"]["value"])

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

    preview_src = ""
    live_preview_error = "Set an image URL to see a live processed preview."
    if image_url.strip():
        try:
            img = fetch_image_from_url(image_url.strip())
            img = process_image_for_label(
                img,
                black_point=black_point,
                white_point=white_point,
                contrast=contrast,
                label_width=preview_width_px,
            )

            draw = ImageDraw.Draw(img)
            try:
                font_path = str(FONT_DIR / selected_font) if selected_font else None
                font = ImageFont.truetype(font_path, size=max(18, img.width // 12)) if font_path else ImageFont.load_default()
            except Exception:
                font = ImageFont.load_default()

            if top_text.strip():
                draw.text((10, 10), top_text.strip(), fill="black", font=font)
            if bottom_text.strip():
                text_bbox = draw.textbbox((0, 0), bottom_text.strip(), font=font)
                text_w = text_bbox[2] - text_bbox[0]
                text_h = text_bbox[3] - text_bbox[1]
                draw.text((max(10, (img.width - text_w) // 2), max(10, img.height - text_h - 10)), bottom_text.strip(), fill="black", font=font)

            img = format_preview_to_media(
                img,
                label_width_px=preview_width_px or img.width,
                label_length_px=preview_length_px,
                rotate_if_needed=True,
            )
            preview_src = render_preview_src(img)
            live_preview_error = ""
        except Exception as exc:
            live_preview_error = f"Preview failed: {exc}"

    return html.div(
        html.label(
            {"class_name": "form-field"},
            html.span({"class_name": "field-label"}, "Image URL"),
            html.input(
                {
                    "value": image_url,
                    "placeholder": "https://example.com/image.jpg",
                    "onChange": handle_url_change,
                    "class_name": "input-control",
                }
            ),
        ),
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
                            font_name,
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
                html.img(
                    {
                        "src": preview_src,
                        "alt": "Processed meme preview",
                        "class_name": "preview-image",
                    }
                ) if preview_src else html.p({"class_name": "preview-error"}, live_preview_error or preview_error or "Upload an image and add text"),
            ),
            html.div(
                {"class_name": "settings-card"},
                html.p({"class_name": "card-title"}, "Meme settings"),
                ImageAdjustControls(black_point, set_black_point, white_point, set_white_point, contrast, set_contrast),
                html.p({"class_name": "setting-row"}, f"File: {image_name or '(none)'}"),
                html.p({"class_name": "setting-row"}, f"URL: {'set' if image_url.strip() else '(none)'}"),
                html.p({"class_name": "setting-row"}, f"Font: {selected_font or 'A'}"),
                html.p({"class_name": "setting-row"}, f"Top: {top_text or '(empty)'}"),
                html.p({"class_name": "setting-row"}, f"Bottom: {bottom_text or '(empty)'}"),
                html.p({"class_name": "setting-note"}, "Image is dithered black/white before text overlay on print."),
            ),
        ),
    )

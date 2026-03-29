from reactpy import component, html, hooks

from .webui_common import (
    ImageAdjustControls,
    fetch_image_from_url,
    format_preview_to_media,
    process_image_for_label,
    render_preview_src,
)


@component
def ImageTab(
    image_url,
    set_image_url,
    black_point,
    set_black_point,
    white_point,
    set_white_point,
    contrast,
    set_contrast,
    preview_width_px=None,
    preview_length_px=None,
):
    image_src, set_image_src = hooks.use_state("")
    image_name, set_image_name = hooks.use_state("")

    def handle_url_change(event):
        set_image_url(event["target"]["value"])

    def handle_image_upload(event):
        files = event["target"]["files"]
        if files and len(files) > 0:
            file = files[0]
            set_image_name(file["name"])
            try:
                set_image_src(f"Image: {file['name']}")
            except Exception as exc:
                set_image_name("")

    preview_src = ""
    preview_error = "Set an image URL to see a live processed preview."
    if image_url.strip():
        try:
            img = fetch_image_from_url(image_url.strip())
            preview_img = process_image_for_label(
                img,
                black_point=black_point,
                white_point=white_point,
                contrast=contrast,
                label_width=preview_width_px,
            )
            preview_img = format_preview_to_media(
                preview_img,
                label_width_px=preview_width_px or preview_img.width,
                label_length_px=preview_length_px,
                rotate_if_needed=True,
            )
            preview_src = render_preview_src(preview_img)
            preview_error = ""
        except Exception as exc:
            preview_error = f"Preview failed: {exc}"

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
                html.img(
                    {
                        "src": preview_src,
                        "alt": "Processed preview",
                        "class_name": "preview-image",
                    }
                ) if preview_src else html.p(
                    {"class_name": "preview-error"},
                    preview_error,
                ),
            ),
            html.div(
                {"class_name": "settings-card"},
                html.p({"class_name": "card-title"}, "Image settings"),
                ImageAdjustControls(black_point, set_black_point, white_point, set_white_point, contrast, set_contrast),
                html.p({"class_name": "setting-row"}, f"File: {image_name or '(none)'}"),
                html.p({"class_name": "setting-row"}, f"URL: {'set' if image_url.strip() else '(none)'}"),
                html.p({"class_name": "setting-row"}, "Image is scaled to label size and rotated automatically if that fits better."),
                html.p({"class_name": "setting-note"}, "Image is converted to dithered black/white on print."),
            ),
        ),
    )

from reactpy import component, html

from label import StikkaLabel
from webui_common import FONT_DIR, FONT_OPTIONS, PreviewSection, make_field, render_preview_src


@component
def AddressLabelTab(
    form_data,
    set_form_data,
    text_height,
    set_text_height,
    selected_font,
    set_selected_font,
    preview_width_mm=62,
    preview_length_mm=None,
):
    def handle_field_change(field_name):
        def _handle_change(event):
            value = event["target"]["value"]
            set_form_data(lambda prev: {**prev, field_name: value})

        return _handle_change

    def handle_font_change(event):
        set_selected_font(event["target"]["value"])

    def handle_text_height_change(event):
        set_text_height(float(event["target"]["value"]))

    auto_preview_height = text_height + (4 * text_height) + (3 * 2) + text_height
    preview_width = preview_width_mm
    preview_height = preview_length_mm if preview_length_mm else auto_preview_height
    preview_src = ""
    preview_error = ""
    try:
        font_path = str(FONT_DIR / selected_font) if selected_font else "A"
        label = StikkaLabel.address_label(
            width=preview_width,
            height=preview_height,
            name=form_data["name"].strip() or "Jane Smith",
            street=form_data["street"].strip() or "456 Elm St",
            zip_code=form_data["zip_code"].strip() or "67890",
            city=form_data["city"].strip() or "Othertown",
            country=form_data["country"].strip() or "",
            font=font_path,
            text_height=text_height,
        )
        preview_image = label.render_image(framing=True)
        preview_src = render_preview_src(preview_image)
    except Exception as exc:
        preview_error = f"Preview unavailable: {exc}"

    return html.div(
        html.div(
            {"class_name": "form-grid"},
            make_field("Full name", "name", form_data["name"], "Jane Smith", handle_field_change),
            make_field("Street", "street", form_data["street"], "456 Elm St", handle_field_change),
            make_field("ZIP code", "zip_code", form_data["zip_code"], "67890", handle_field_change),
            make_field("City", "city", form_data["city"], "Othertown", handle_field_change),
            make_field("Country", "country", form_data["country"], "Canada", handle_field_change),
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
                        [html.option({"key": font_name, "value": font_name}, font_name) for font_name in FONT_OPTIONS]
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

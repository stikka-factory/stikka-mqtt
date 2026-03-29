from reactpy import component, html

from label.label import StikkaLabel
from .webui_common import FONT_DIR, FONT_OPTIONS, PreviewSection, render_preview_src


@component
def SimpleLabel(
    text_value,
    set_text,
    text_height,
    set_text_height,
    selected_font,
    set_selected_font,
    preview_width_mm=62,
    preview_length_mm=None,
):
    def handle_text_change(event):
        set_text(event["target"]["value"])

    def handle_height_change(event):
        set_text_height(float(event["target"]["value"]))

    def handle_font_change(event):
        set_selected_font(event["target"]["value"])

    preview_src = ""
    preview_error = ""
    try:
        lines = text_value.strip().split("\n") if text_value.strip() else [""]
        num_lines = len(lines)
        line_spacing = 2
        text_block_height = text_height + (num_lines * text_height) + ((num_lines - 1) * line_spacing) + text_height
        label_height = preview_length_mm if preview_length_mm else text_block_height
        label_width = preview_width_mm

        label = StikkaLabel(label_width, label_height)
        font_path = str(FONT_DIR / selected_font) if selected_font else "A"

        y_pos = text_height
        for line in lines:
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
        preview_src = render_preview_src(preview_image)
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
                            font_name,
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

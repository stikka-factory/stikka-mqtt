import json
import threading
import re
from PIL import Image

from reactpy import component, html, hooks, web

from .webui_common import (
    FONT_OPTIONS,
    ImageAdjustControls,
    draw_overlay_text,
    fetch_image_from_url,
    format_preview_to_media,
    image_from_uploaded_payload,
    process_image_for_label,
    render_preview_src,
)


_UPLOAD_MODULE = web.module_from_string(
        "stikka-upload-input",
        """
import * as React from "https://esm.sh/react@18";
import * as ReactDOM from "https://esm.sh/react-dom@18";

export function DataUrlFileInput(props) {
    const accept = props.accept || "image/*";
    const className = props.className || props.class_name || "";

    function emitPayload(payload) {
        const cbSnake = props.on_data;
        const cbCamel = props.onData;
        if (typeof cbSnake === "function") {
            cbSnake(payload);
        }
        if (typeof cbCamel === "function") {
            cbCamel(payload);
        }
    }

    function downscaleToDataUrl(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onerror = () => reject(new Error("read_error"));
            reader.onload = () => {
                const src = String(reader.result || "");
                const img = new Image();
                img.onerror = () => reject(new Error("image_decode_error"));
                img.onload = () => {
                    const maxDim = 1600;
                    let w = img.width;
                    let h = img.height;
                    const scale = Math.min(1, maxDim / Math.max(w, h));
                    w = Math.max(1, Math.round(w * scale));
                    h = Math.max(1, Math.round(h * scale));

                    const canvas = document.createElement("canvas");
                    canvas.width = w;
                    canvas.height = h;
                    const ctx = canvas.getContext("2d");
                    if (!ctx) {
                        reject(new Error("canvas_context_error"));
                        return;
                    }
                    ctx.drawImage(img, 0, 0, w, h);

                    // JPEG keeps payloads much smaller than PNG for photos.
                    // For transparent images, fallback to PNG if JPEG fails.
                    let dataUrl = canvas.toDataURL("image/jpeg", 0.85);
                    if (!dataUrl || dataUrl === "data:," || dataUrl.length < 32) {
                        dataUrl = canvas.toDataURL("image/png");
                    }
                    resolve(dataUrl);
                };
                img.src = src;
            };
            reader.readAsDataURL(file);
        });
    }

    function handleChange(event) {
        const file = event?.target?.files?.[0];
        if (!file) {
            emitPayload({ data_url: "", name: "" });
            return;
        }

        downscaleToDataUrl(file)
            .then((dataUrl) => {
                emitPayload({
                    data_url: String(dataUrl || ""),
                    name: file.name || "uploaded-image",
                });
            })
            .catch((err) => {
                emitPayload({
                    data_url: "",
                    name: file.name || "uploaded-image",
                    error: String(err && err.message ? err.message : "read_error"),
                });
            });
    }

    return React.createElement("input", {
        type: "file",
        accept,
        className,
        onChange: handleChange,
    });
}

export function bind(node) {
    const root = ReactDOM.createRoot(node);
    return {
        create: (component, props, children) =>
            React.createElement(component, wrapEventHandlers(props || {}), ...(children || [])),
        render: (element) => root.render(element),
        unmount: () => root.unmount(),
    };
}

function wrapEventHandlers(props) {
    const newProps = Object.assign({}, props || {});
    for (const [key, value] of Object.entries(props || {})) {
        if (typeof value === "function") {
            newProps[key] = makeJsonSafeEventHandler(value);
        }
    }
    return newProps;
}

function makeJsonSafeEventHandler(oldHandler) {
    return function safeEventHandler() {
        oldHandler(
            ...Array.from(arguments).filter((value) => {
                if (typeof value === "object" && value && value.nativeEvent) {
                    return true;
                }
                try {
                    JSON.stringify(value);
                } catch (err) {
                    return false;
                }
                return true;
            }),
        );
    };
}
""",
)
DataUrlFileInput = web.export(_UPLOAD_MODULE, "DataUrlFileInput")


@component
def MediaTab(
    image_url,
    set_image_url,
    uploaded_image_payload,
    set_uploaded_image_payload,
    use_white_background,
    set_use_white_background,
    overlay_text,
    set_overlay_text,
    text_black,
    set_text_black,
    text_align,
    set_text_align,
    crop_to_center,
    set_crop_to_center,
    rotate_image,
    set_rotate_image,
    image_offset_x,
    set_image_offset_x,
    image_offset_y,
    set_image_offset_y,
    text_vertical_align,
    set_text_vertical_align,
    text_rotate_90,
    set_text_rotate_90,
    text_offset_x,
    set_text_offset_x,
    text_offset_y,
    set_text_offset_y,
    selected_font,
    set_selected_font,
    text_size,
    set_text_size,
    black_point,
    set_black_point,
    white_point,
    set_white_point,
    contrast,
    set_contrast,
    preview_width_px=None,
    preview_length_px=None,
):
    preview_error, set_preview_error = hooks.use_state("Set an image URL or fetch a cat image to preview.")
    image_name, set_image_name = hooks.use_state("")
    is_loading_cat, set_is_loading_cat = hooks.use_state(False)
    is_loading_dog, set_is_loading_dog = hooks.use_state(False)

    def _pick(obj, key, default=None):
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(key, default)
        try:
            return obj[key]
        except Exception:
            pass
        return getattr(obj, key, default)

    def _extract_upload_payload(obj):
        def _looks_like_base64_string(value):
            if not isinstance(value, str):
                return False
            text = value.strip()
            if len(text) < 128:
                return False
            if any(ch.isspace() for ch in text):
                return False
            return re.fullmatch(r"[A-Za-z0-9+/=_-]+", text) is not None

        if obj is None:
            return None

        if isinstance(obj, (bytes, bytearray)):
            return obj

        if isinstance(obj, str):
            text = obj.strip()
            if text.startswith("data:image"):
                return text
            # Path-like values are accepted and validated by the decoder.
            if "/" in text or text.startswith("."):
                return text
            if _looks_like_base64_string(text):
                return text
            return None

        if isinstance(obj, list):
            # A list of ints is already bytes payload.
            if obj and all(isinstance(item, int) for item in obj):
                return obj
            for item in obj:
                found = _extract_upload_payload(item)
                if found is not None:
                    return found
            return None

        if isinstance(obj, dict):
            for key in [
                "data_url",
                "data",
                "content",
                "base64",
                "file",
                "blob",
                "path",
                "tempfile",
                "value",
                "result",
                "files",
                "target",
                "currentTarget",
            ]:
                if key in obj and obj[key] is not None:
                    found = _extract_upload_payload(obj[key])
                    if found is not None:
                        return found
            # Last-resort recursive walk through all values for unknown event shapes.
            for value in obj.values():
                found = _extract_upload_payload(value)
                if found is not None:
                    return found
            return None

        # Generic proxy/object fallback.
        for key in [
            "data_url",
            "data",
            "content",
            "base64",
            "file",
            "blob",
            "path",
            "tempfile",
            "value",
            "result",
            "files",
            "target",
            "currentTarget",
        ]:
            value = _pick(obj, key)
            if value is not None:
                found = _extract_upload_payload(value)
                if found is not None:
                    return found
        return None

    def handle_url_change(event):
        set_image_url(event["target"]["value"])
        set_uploaded_image_payload("")
        set_use_white_background(False)

    def handle_data_url_upload(payload):
        try:
            if payload is None:
                set_preview_error("Upload failed. Please select the image again.")
                return
            data_url = _pick(payload, "data_url", "") or ""
            file_name = _pick(payload, "name", "uploaded-image") or "uploaded-image"
            error_text = _pick(payload, "error", "") or ""
            if error_text:
                set_preview_error("Browser file read failed. Please select the image again.")
                return
            text = data_url.strip() if isinstance(data_url, str) else ""
            if not text:
                set_preview_error("No file selected.")
                return
            if not text.startswith("data:image"):
                set_preview_error("Browser file read failed. Please select the image again.")
                return
            set_uploaded_image_payload(text)
            set_image_url("")
            set_use_white_background(False)
            set_image_name(file_name)
            set_preview_error(f"Loaded upload: {file_name}")
        except Exception as exc:
            set_preview_error(f"Upload failed: {exc}")

    def handle_use_white_background(event):
        del event
        set_image_url("")
        set_uploaded_image_payload("")
        set_use_white_background(True)
        set_image_name("White background")
        set_preview_error("")

    def handle_overlay_text_change(event):
        set_overlay_text(event["target"]["value"])

    def handle_text_black_change(event):
        set_text_black(bool(event["target"].get("checked", False)))

    def handle_text_align_change(event):
        set_text_align(event["target"]["value"])

    def handle_crop_to_center_change(event):
        set_crop_to_center(bool(event["target"].get("checked", False)))

    def handle_rotate_image_change(event):
        set_rotate_image(bool(event["target"].get("checked", False)))

    def handle_image_offset_x_change(event):
        set_image_offset_x(int(event["target"]["value"]))

    def handle_image_offset_y_change(event):
        set_image_offset_y(int(event["target"]["value"]))

    def handle_text_vertical_align_change(event):
        set_text_vertical_align(event["target"]["value"])

    def handle_text_rotate_90_change(event):
        set_text_rotate_90(bool(event["target"].get("checked", False)))

    def handle_text_offset_x_change(event):
        set_text_offset_x(int(event["target"]["value"]))

    def handle_text_offset_y_change(event):
        set_text_offset_y(int(event["target"]["value"]))

    def handle_font_change(event):
        set_selected_font(event["target"]["value"])

    def handle_text_size_change(event):
        set_text_size(int(event["target"]["value"]))

    def handle_fetch_cat(event):
        del event
        set_is_loading_cat(True)
        set_preview_error("Loading cat image...")

        def fetch_cat():
            try:
                import urllib.error
                import urllib.request

                req = urllib.request.Request("https://api.thecatapi.com/v1/images/search")
                req.add_header("User-Agent", "Mozilla/5.0 (compatible; Stikka-NG/1.0)")
                response = urllib.request.urlopen(req, timeout=10)
                data = json.loads(response.read().decode())
                if data and len(data) > 0:
                    set_image_url(data[0]["url"])
                    set_uploaded_image_payload("")
                    set_use_white_background(False)
                    set_preview_error("")
                else:
                    set_preview_error("No cat images found.")
            except urllib.error.HTTPError as exc:
                set_preview_error(f"HTTP Error {exc.code}: Failed to fetch cat image")
            except urllib.error.URLError as exc:
                set_preview_error(f"Network error: {exc.reason}")
            except Exception as exc:
                set_preview_error(f"Failed to fetch cat image: {exc}")
            finally:
                set_is_loading_cat(False)

        threading.Thread(target=fetch_cat, daemon=True).start()

    def handle_fetch_dog(event):
        del event
        set_is_loading_dog(True)
        set_preview_error("Loading dog image...")

        def fetch_dog():
            try:
                import urllib.error
                import urllib.request

                req = urllib.request.Request("https://dog.ceo/api/breeds/image/random")
                req.add_header("User-Agent", "Mozilla/5.0 (compatible; Stikka-NG/1.0)")
                response = urllib.request.urlopen(req, timeout=10)
                data = json.loads(response.read().decode())
                dog_url = data.get("message")
                if dog_url:
                    set_image_url(dog_url)
                    set_uploaded_image_payload("")
                    set_use_white_background(False)
                    set_preview_error("")
                else:
                    set_preview_error("No dog image found.")
            except urllib.error.HTTPError as exc:
                set_preview_error(f"HTTP Error {exc.code}: Failed to fetch dog image")
            except urllib.error.URLError as exc:
                set_preview_error(f"Network error: {exc.reason}")
            except Exception as exc:
                set_preview_error(f"Failed to fetch dog image: {exc}")
            finally:
                set_is_loading_dog(False)

        threading.Thread(target=fetch_dog, daemon=True).start()

    preview_src = ""
    live_preview_error = preview_error
    upload_payload_info = "set" if uploaded_image_payload else "(none)"
    if image_url.strip() or uploaded_image_payload or use_white_background:
        try:
            if uploaded_image_payload:
                img = image_from_uploaded_payload(uploaded_image_payload)
            elif image_url.strip():
                img = fetch_image_from_url(image_url.strip())
            else:
                blank_width = max(1, int(preview_width_px or 696))
                blank_height = max(1, int(preview_length_px or blank_width))
                img = Image.new("RGB", (blank_width, blank_height), "white")
            img = process_image_for_label(
                img,
                black_point=black_point,
                white_point=white_point,
                contrast=contrast,
                label_width=preview_width_px,
            )
            img = format_preview_to_media(
                img,
                label_width_px=preview_width_px or img.width,
                label_length_px=preview_length_px,
                rotate=rotate_image,
                crop_to_center=crop_to_center,
                image_offset_x=image_offset_x,
                image_offset_y=image_offset_y,
            )
            draw_overlay_text(
                img,
                overlay_text=overlay_text,
                selected_font=selected_font,
                text_size=text_size,
                text_black=text_black,
                align=text_align,
                vertical_align=text_vertical_align,
                offset_x=text_offset_x,
                offset_y=text_offset_y,
                rotate_90=text_rotate_90,
            )
            preview_src = render_preview_src(img)
            live_preview_error = ""
        except Exception as exc:
            live_preview_error = f"Preview failed: {exc}"

    return html.div(
        {"class_name": "media-tab-grid"},
        html.details(
            {"class_name": "overlay-foldout", "open": True},
            html.summary({"class_name": "overlay-summary"}, "Image"),
            html.div(
                {"class_name": "foldout-grid image-controls-grid"},
                html.label(
                    {"class_name": "form-field image-url-field"},
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
                    {"class_name": "form-field image-file-field"},
                    html.span({"class_name": "field-label"}, "Select image file"),
                    DataUrlFileInput(
                        {
                            "accept": "image/*",
                            "on_data": handle_data_url_upload,
                            "class_name": "image-input",
                        }
                    ),
                ),
                html.button(
                    {
                        "onClick": handle_fetch_cat,
                        "disabled": is_loading_cat,
                        "class_name": "btn scan-btn foldout-action-btn image-cat-btn",
                    },
                    "Loading..." if is_loading_cat else "Fetch random cat",
                ),
                html.button(
                    {
                        "onClick": handle_fetch_dog,
                        "disabled": is_loading_dog,
                        "class_name": "btn scan-btn foldout-action-btn image-dog-btn",
                    },
                    "Loading..." if is_loading_dog else "Fetch random dog",
                ),
                html.button(
                    {
                        "onClick": handle_use_white_background,
                        "class_name": "btn scan-btn foldout-action-btn image-clear-btn",
                    },
                    "Use white background",
                ),
                html.label(
                    {"class_name": "form-field checkbox-field image-crop-field"},
                    html.span({"class_name": "field-label"}, "Image fit mode"),
                    html.label(
                        {"class_name": "check-inline"},
                        html.input(
                            {
                                "type": "checkbox",
                                "checked": bool(crop_to_center),
                                "onChange": handle_crop_to_center_change,
                            }
                        ),
                        html.span("Scale to fill and center-crop"),
                    ),
                ),
                html.label(
                    {"class_name": "form-field checkbox-field image-rotate-field"},
                    html.span({"class_name": "field-label"}, "Rotate image"),
                    html.label(
                        {"class_name": "check-inline"},
                        html.input(
                            {
                                "type": "checkbox",
                                "checked": bool(rotate_image),
                                "onChange": handle_rotate_image_change,
                            }
                        ),
                        html.span("Rotate 90° clockwise before scaling."),
                    ),
                ),
                html.label(
                    {"class_name": "form-field image-offset-x-field"},
                    html.div(
                        {"class_name": "range-head"},
                        html.span({"class_name": "field-label"}, "Horizontal image offset"),
                        html.span({"class_name": "range-value"}, f"{image_offset_x}px"),
                    ),
                    html.input(
                        {
                            "type": "range",
                            "min": "-1500",
                            "max": "1500",
                            "step": "2",
                            "value": str(image_offset_x),
                            "onChange": handle_image_offset_x_change,
                            "class_name": "range-control",
                        }
                    ),
                ),
                html.label(
                    {"class_name": "form-field image-offset-y-field"},
                    html.div(
                        {"class_name": "range-head"},
                        html.span({"class_name": "field-label"}, "Vertical image offset"),
                        html.span({"class_name": "range-value"}, f"{image_offset_y}px"),
                    ),
                    html.input(
                        {
                            "type": "range",
                            "min": "-1500",
                            "max": "1500",
                            "step": "2",
                            "value": str(image_offset_y),
                            "onChange": handle_image_offset_y_change,
                            "class_name": "range-control",
                        }
                    ),
                ),
            ),
        ),
        html.details(
            {"class_name": "overlay-foldout", "open": True},
            html.summary({"class_name": "overlay-summary"}, "Text"),
            html.div(
                {"class_name": "foldout-grid text-controls-grid"},
                html.label(
                    {"class_name": "form-field text-overlay-field"},
                    html.span({"class_name": "field-label"}, "Multiline text overlay"),
                    html.textarea(
                        {
                            "value": overlay_text,
                            "placeholder": "Add one or more lines",
                            "onChange": handle_overlay_text_change,
                            "class_name": "input-control textarea-control",
                            "rows": "4",
                        }
                    ),
                ),
                html.label(
                    {"class_name": "form-field text-font-field"},
                    html.span({"class_name": "field-label"}, "Overlay font"),
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
                    {"class_name": "form-field text-color-field"},
                    html.span({"class_name": "field-label"}, "Text color mode"),
                    html.label(
                        {"class_name": "check-inline"},
                        html.input(
                            {
                                "type": "checkbox",
                                "checked": bool(text_black),
                                "onChange": handle_text_black_change,
                            }
                        ),
                        html.span("Black text"),
                    ),
                ),
                html.label(
                    {"class_name": "form-field text-vertical-field"},
                    html.span({"class_name": "field-label"}, "Vertical alignment"),
                    html.select(
                        {
                            "value": text_vertical_align,
                            "onChange": handle_text_vertical_align_change,
                            "class_name": "input-control",
                        },
                        html.option({"value": "top"}, "Top"),
                        html.option({"value": "center"}, "Center"),
                        html.option({"value": "bottom"}, "Bottom"),
                    ),
                ),
                html.label(
                    {"class_name": "form-field text-horizontal-field"},
                    html.span({"class_name": "field-label"}, "Horizontal alignment"),
                    html.select(
                        {
                            "value": text_align,
                            "onChange": handle_text_align_change,
                            "class_name": "input-control",
                        },
                        html.option({"value": "left"}, "Left"),
                        html.option({"value": "center"}, "Center"),
                        html.option({"value": "right"}, "Right"),
                    ),
                ),
                html.label(
                    {"class_name": "form-field text-rotate-field"},
                    html.span({"class_name": "field-label"}, "Text rotation"),
                    html.label(
                        {"class_name": "check-inline"},
                        html.input(
                            {
                                "type": "checkbox",
                                "checked": bool(text_rotate_90),
                                "onChange": handle_text_rotate_90_change,
                            }
                        ),
                        html.span("Rotate text 90° clockwise."),
                    ),
                ),
                html.label(
                    {"class_name": "form-field text-size-field"},
                    html.div(
                        {"class_name": "range-head"},
                        html.span({"class_name": "field-label"}, "Text size"),
                        html.span({"class_name": "range-value"}, f"{text_size}px"),
                    ),
                    html.input(
                        {
                            "type": "range",
                            "min": "16",
                            "max": "96",
                            "step": "1",
                            "value": str(text_size),
                            "onChange": handle_text_size_change,
                            "class_name": "range-control",
                        }
                    ),
                ),
                html.label(
                    {"class_name": "form-field text-offset-x-field"},
                    html.div(
                        {"class_name": "range-head"},
                        html.span({"class_name": "field-label"}, "Horizontal text offset"),
                        html.span({"class_name": "range-value"}, f"{text_offset_x}px"),
                    ),
                    html.input(
                        {
                            "type": "range",
                            "min": "-1500",
                            "max": "1500",
                            "step": "2",
                            "value": str(text_offset_x),
                            "onChange": handle_text_offset_x_change,
                            "class_name": "range-control",
                        }
                    ),
                ),
                html.label(
                    {"class_name": "form-field text-offset-y-field"},
                    html.div(
                        {"class_name": "range-head"},
                        html.span({"class_name": "field-label"}, "Vertical text offset"),
                        html.span({"class_name": "range-value"}, f"{text_offset_y}px"),
                    ),
                    html.input(
                        {
                            "type": "range",
                            "min": "-1500",
                            "max": "1500",
                            "step": "2",
                            "value": str(text_offset_y),
                            "onChange": handle_text_offset_y_change,
                            "class_name": "range-control",
                        }
                    ),
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
                        "alt": "Processed media preview",
                        "class_name": "preview-image",
                    }
                ) if preview_src else html.p({"class_name": "preview-error"}, live_preview_error),
            ),
            html.div(
                {"class_name": "settings-card"},
                ImageAdjustControls(black_point, set_black_point, white_point, set_white_point, contrast, set_contrast),
                html.p({"class_name": "setting-row"}, f"File: {image_name or '(none)'}"),
                html.p({"class_name": "setting-row"}, f"URL: {'set' if image_url.strip() else '(none)'}"),
                html.p({"class_name": "setting-row"}, f"Upload: {upload_payload_info}"),
                html.p({"class_name": "setting-row"}, f"White background: {'yes' if use_white_background else 'no'}"),
                html.p({"class_name": "setting-row"}, f"Crop mode: {'center-crop' if crop_to_center else 'fit whole image'}"),
                html.p({"class_name": "setting-row"}, f"Rotate: {'90 deg CW' if rotate_image else 'no'}"),
                html.p({"class_name": "setting-row"}, f"Image offset: X {image_offset_x}px / Y {image_offset_y}px"),
                html.p({"class_name": "setting-row"}, f"Overlay: {'set' if overlay_text.strip() else '(empty)'}"),
                html.p({"class_name": "setting-row"}, f"Text color: {'black' if text_black else 'white + outline'}"),
                html.p({"class_name": "setting-row"}, f"Text align: {text_align} / {text_vertical_align}"),
                html.p({"class_name": "setting-row"}, f"Text rotate: {'90 deg CW' if text_rotate_90 else 'no'}"),
                html.p({"class_name": "setting-row"}, f"Text offset: X {text_offset_x}px / Y {text_offset_y}px"),
                html.p({"class_name": "setting-row"}, f"Font: {selected_font or 'A'}"),
                html.p({"class_name": "setting-row"}, f"Text size: {text_size}px"),
                html.p({"class_name": "setting-note"}, "Image can be fit or center-cropped to media size. Text overlay supports multiline and alignment."),
            ),
        ),
    )

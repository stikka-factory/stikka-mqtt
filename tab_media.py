import json
import threading
import re

from reactpy import component, html, hooks, web

from webui_common import (
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
    top_text,
    set_top_text,
    bottom_text,
    set_bottom_text,
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
            set_image_name(file_name)
            set_preview_error(f"Loaded upload: {file_name}")
        except Exception as exc:
            set_preview_error(f"Upload failed: {exc}")

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
    if image_url.strip() or uploaded_image_payload:
        try:
            if uploaded_image_payload:
                img = image_from_uploaded_payload(uploaded_image_payload)
            else:
                img = fetch_image_from_url(image_url.strip())
            img = process_image_for_label(
                img,
                black_point=black_point,
                white_point=white_point,
                contrast=contrast,
                label_width=preview_width_px,
            )
            draw_overlay_text(
                img,
                top_text=top_text,
                bottom_text=bottom_text,
                selected_font=selected_font,
                text_size=text_size,
            )

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
        html.details(
            {"class_name": "overlay-foldout", "open": True},
            html.summary({"class_name": "overlay-summary"}, "Image source"),
            html.div(
                {"class_name": "foldout-grid"},
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
                        "class_name": "btn scan-btn foldout-action-btn",
                    },
                    "Loading..." if is_loading_cat else "Fetch random cat",
                ),
                html.button(
                    {
                        "onClick": handle_fetch_dog,
                        "disabled": is_loading_dog,
                        "class_name": "btn scan-btn foldout-action-btn",
                    },
                    "Loading..." if is_loading_dog else "Fetch random dog",
                ),
            ),
        ),
        html.details(
            {"class_name": "overlay-foldout"},
            html.summary({"class_name": "overlay-summary"}, "Text overlay"),
            html.div(
                {"class_name": "foldout-grid"},
                html.label(
                    {"class_name": "form-field"},
                    html.span({"class_name": "field-label"}, "Top text (optional)"),
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
                    html.span({"class_name": "field-label"}, "Bottom text (optional)"),
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
                    {"class_name": "form-field"},
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
                html.p({"class_name": "card-title"}, "Media settings"),
                ImageAdjustControls(black_point, set_black_point, white_point, set_white_point, contrast, set_contrast),
                html.p({"class_name": "setting-row"}, f"File: {image_name or '(none)'}"),
                html.p({"class_name": "setting-row"}, f"URL: {'set' if image_url.strip() else '(none)'}"),
                html.p({"class_name": "setting-row"}, f"Upload: {upload_payload_info}"),
                html.p({"class_name": "setting-row"}, f"Top text: {top_text or '(empty)'}"),
                html.p({"class_name": "setting-row"}, f"Bottom text: {bottom_text or '(empty)'}"),
                html.p({"class_name": "setting-row"}, f"Font: {selected_font or 'A'}"),
                html.p({"class_name": "setting-row"}, f"Text size: {text_size}px"),
                html.p({"class_name": "setting-note"}, "Overlay text is white with a black outline. Image is scaled to label size and rotated automatically if needed."),
            ),
        ),
    )

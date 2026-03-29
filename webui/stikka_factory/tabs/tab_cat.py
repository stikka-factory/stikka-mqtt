import json
import threading

from reactpy import component, html, hooks

from .webui_common import (
    ImageAdjustControls,
    fetch_image_from_url,
    format_preview_to_media,
    process_image_for_label,
    render_preview_src,
)


@component
def CatTab(
    cat_image_url,
    set_cat_image_url,
    black_point,
    set_black_point,
    white_point,
    set_white_point,
    contrast,
    set_contrast,
    preview_width_px=None,
    preview_length_px=None,
):
    preview_error, set_preview_error = hooks.use_state("Click 'Fetch Cat' to get a random cat image")
    is_loading, set_is_loading = hooks.use_state(False)

    def handle_fetch_cat(event):
        del event
        set_is_loading(True)
        set_preview_error("Loading...")

        def fetch_cat():
            try:
                import urllib.error
                import urllib.request

                url = "https://api.thecatapi.com/v1/images/search"
                req = urllib.request.Request(url)
                req.add_header("User-Agent", "Mozilla/5.0 (compatible; Stikka-NG/1.0)")

                try:
                    response = urllib.request.urlopen(req, timeout=10)
                    data = json.loads(response.read().decode())
                    if data and len(data) > 0:
                        cat_url = data[0]["url"]
                        set_cat_image_url(cat_url)
                        set_preview_error("")
                    else:
                        set_preview_error("No cat images found")
                except urllib.error.HTTPError as exc:
                    set_preview_error(f"HTTP Error {exc.code}: Failed to fetch cat image")
                except urllib.error.URLError as exc:
                    set_preview_error(f"Network error: {exc.reason}")
                except Exception as exc:
                    set_preview_error(f"Error: {exc}")
            except ImportError:
                set_preview_error("Network libraries not available")
            finally:
                set_is_loading(False)

        thread = threading.Thread(target=fetch_cat, daemon=True)
        thread.start()

    preview_src = ""
    if cat_image_url:
        try:
            preview_img = fetch_image_from_url(cat_image_url)
            preview_img = process_image_for_label(
                preview_img,
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
        except Exception as exc:
            preview_error = f"Preview failed: {exc}"

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
                        "src": preview_src,
                        "alt": "Random cat",
                        "class_name": "cat-image",
                    }
                )
                if preview_src
                else html.div(
                    {"class_name": "preview-error"},
                    preview_error,
                ),
            ),
            html.div(
                {"class_name": "settings-card"},
                html.p({"class_name": "card-title"}, "Cat settings"),
                ImageAdjustControls(black_point, set_black_point, white_point, set_white_point, contrast, set_contrast),
                html.p({"class_name": "setting-row"}, "Fetches random cat images from The Cat API"),
                html.p({"class_name": "setting-note"}, "Attribution: Images provided by thecatapi.com"),
                html.p({"class_name": "setting-note"}, "Note: Requires internet connection"),
            ),
        ),
    )

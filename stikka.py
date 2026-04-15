"""
stikka.py
=========
Application entry point for Stikka-NG.

This module wires together startup tasks (config loading, statistics
initialisation, font-preview generation, static-file serving) and hands
control to NiceGUI's event loop.

Run with::

    uv run stikka.py

or directly::

    python stikka.py
"""

from pathlib import Path

from nicegui import app, ui

import stikka_webui as webui
import stikka_label_helper as lh

log = lh.log


def startup() -> None:
    """Execute all one-time startup tasks before the server begins accepting requests.

    - Loads ``config.json`` and applies the colour theme.
    - Creates the print-statistics CSV if it does not exist.
    - Generates ``docs/fonts_preview.jpg`` for the Fonts tab.
    - Registers ``/fonts`` as a static-file route.
    - Sets the browser tab title from the config ``name`` field.
    """
    webui.load_config()
    webui.init_stats_csv()

    fonts_dir = Path(webui.config.get('fonts_dir', 'fonts'))
    use_system_fonts = webui.config.get('use_system_fonts', False)
    lh.generate_fonts_preview(font_dir=fonts_dir, use_system_fonts=use_system_fonts)

    app.add_static_files('/fonts', 'fonts')
    app.title = webui.config['name']
    log.info(f"Stikka-NG '{app.title}' starting up...")


if __name__ in {'__main__', '__mp_main__'}:
    startup()

    host = webui.config.get('host', '0.0.0.0')
    port = int(webui.config.get('port', 8080))
    ui.run(host=host, port=port)

from pathlib import Path

from nicegui import app, ui

import stikka_config as cfg
import stikka_label_helper as lh
import stikka_webui  # registers page routes

log = lh.log


def startup() -> None:
    cfg.load_config()
    cfg.init_stats_csv()

    fonts_dir = Path(cfg.config.get('fonts_dir', 'fonts'))
    use_system_fonts = cfg.config.get('use_system_fonts', False)
    lh.generate_fonts_preview(font_dir=fonts_dir, use_system_fonts=use_system_fonts)

    app.add_static_files('/fonts', 'fonts')
    app.title = cfg.config['name']
    log.info(f"Stikka-NG '{app.title}' starting up...")


if __name__ in {'__main__', '__mp_main__'}:
    startup()

    host = cfg.config.get('host', '0.0.0.0')
    port = int(cfg.config.get('port', 8080))
    ui.run(host=host, port=port)

import subprocess
from pathlib import Path

from nicegui import app, ui

import stikka_config as cfg
import stikka_label_helper as lh
import stikka_webui  # registers page routes

log = lh.log


def _ensure_self_signed_cert(cert_path: Path, key_path: Path) -> None:
    """Generate a self-signed certificate/key pair if they don't exist yet."""
    if cert_path.exists() and key_path.exists():
        return
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    log.info(f'Generating self-signed TLS certificate at {cert_path} ...')
    subprocess.run(
        [
            'openssl', 'req', '-x509', '-newkey', 'rsa:2048',
            '-keyout', str(key_path),
            '-out', str(cert_path),
            '-days', '3650',
            '-nodes',
            '-subj', '/CN=stikka-ng',
        ],
        check=True,
        capture_output=True,
    )
    log.info('Self-signed certificate generated.')


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

    ssl_enabled = cfg.config.get('ssl', False)
    ssl_kwargs: dict = {}
    if ssl_enabled:
        cert_path = Path(cfg.config.get('ssl_certfile', 'certs/cert.pem'))
        key_path = Path(cfg.config.get('ssl_keyfile', 'certs/key.pem'))
        _ensure_self_signed_cert(cert_path, key_path)
        ssl_kwargs = {'ssl_certfile': str(cert_path), 'ssl_keyfile': str(key_path)}
        log.info(f'HTTPS enabled (cert={cert_path}, key={key_path})')

    ui.run(host=host, port=port, **ssl_kwargs)

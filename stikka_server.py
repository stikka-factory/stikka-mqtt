"""Stikka-NG FastAPI server — config + printer management only.

The frontend (Vite/TypeScript) handles all image rendering and processing.
This server only:
  - Serves the pre-built Vite frontend from frontend/dist/
  - Serves fonts at /fonts/
  - Exposes a REST API for printer info, config management, and raw printing

API contract (matches frontend/src/api.ts):
  GET  /api/appinfo            → AppInfo
  GET  /api/printers           → PrinterInfo[]
  GET  /api/fonts              → FontInfo[]
  POST /api/print              → { printerIndex, image: dataURL }
  POST /api/zpl/raw            → { printerIndex, zpl }
  POST /api/zpl/preview        → { printerIndex, zpl } → PNG image
  GET  /api/random/{kind}      → JPEG image (cat | dog | dino)
  GET  /api/config             → JSON text  (requires X-Config-Password)
  POST /api/config             → JSON body  (requires X-Config-Password)
  GET  /api/printers/scan      → ScannedPrinter[]  (requires X-Config-Password)
"""
from __future__ import annotations

import asyncio
import base64
import concurrent.futures as _cf
import ipaddress as _ipaddress
import json
import re as _re
import secrets
import socket as _socket
import subprocess
from io import BytesIO
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, field_validator

import stikka_config as cfg
import stikka_print_it as pi
from stikka_label_helper import log, list_fonts

# ---------------------------------------------------------------------------
# Config loading (without NiceGUI colour bindings)
# ---------------------------------------------------------------------------

def _load_config() -> None:
    """Load config.json and parse label format shorthands."""
    with open('config.json', encoding='utf-8') as f:
        cfg.config = json.load(f)
    for p in cfg.config.get('printers', []):
        cfg.parse_label_format(p['label'])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20 MB hard cap


def _decode_image(data_url: str) -> Image.Image:
    """Decode a base64 data URL to a PIL Image."""
    # Rough upper-bound check before decoding
    if len(data_url) > _MAX_IMAGE_BYTES * 4 // 3 + 256:
        raise ValueError('Image data URL exceeds maximum allowed size')
    if ',' in data_url:
        _, b64 = data_url.split(',', 1)
    else:
        b64 = data_url
    img_bytes = base64.b64decode(b64)
    if len(img_bytes) > _MAX_IMAGE_BYTES:
        raise ValueError('Decoded image exceeds maximum allowed size')
    return Image.open(BytesIO(img_bytes))


def _check_password(provided: str) -> bool:
    """Timing-safe comparison against config_pwd."""
    expected = cfg.config.get('config_pwd', '')
    # Both operands must be the same type; ensure str
    return secrets.compare_digest(provided, expected)


def _get_printer(index: int) -> dict:
    """Return printer config dict by index, raising 400 on invalid index."""
    printers = cfg.config.get('printers', [])
    if index < 0 or index >= len(printers):
        raise HTTPException(status_code=400, detail=f'Invalid printer index: {index}')
    return printers[index]


def _dispatch_print(img: Image.Image, printer: dict, source_kind: str = 'none') -> None:
    """Send a pre-rendered PIL image to the appropriate printer backend."""
    printer_type = printer.get('type', '')
    label = printer['label']
    dpi = printer.get('dpi', 300)
    label_width_mm = label.get('width', 80.0)
    label_length_mm = label.get('length', 0.0)
    label_cut = label.get('cut', True)
    vertical_offset_mm = label.get('vertical_offset', 0.0)

    if printer_type == 'file':
        # Debug printer — save PNG to output/
        out_dir = Path('output')
        out_dir.mkdir(exist_ok=True)
        from datetime import datetime
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        out_path = out_dir / f'stikka_{ts}.png'
        img.save(out_path)
        log.info(f'[file printer] Saved label to {out_path}')

    elif printer_type == 'brother_ql':
        # Extract model token from the printer name (e.g. "QL-720NW")
        name_parts = printer.get('name', '').split()
        model = name_parts[-1] if name_parts else ''
        if not model:
            raise RuntimeError(
                f'Cannot determine Brother QL model from printer name: {printer["name"]!r}'
            )
        pi.print_ql(
            img,
            identfier=printer['connection'],
            backend_name=printer.get('backend', 'pyusb'),
            model=model,
            label_width_mm=label_width_mm,
            label_length_mm=label_length_mm,
            dpi=dpi,
            cut=label_cut,
        )

    elif printer_type == 'seiko_slp':
        pi.print_seiko(img, printer_config=printer)

    elif printer_type == 'zpl':
        zpl_data = pi.img_to_zpl(
            img,
            dpi=dpi,
            label_width_mm=label_width_mm,
            label_length_mm=label_length_mm,
            vertical_offset_mm=vertical_offset_mm,
        )
        host, port_str = printer['connection'].split(':')
        pi.print_zpl(zpl_data, host=host, port=int(port_str))

    else:
        raise RuntimeError(f'Unknown printer type: {printer_type!r}')

    cfg.record_print(source_kind)


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class PrintRequest(BaseModel):
    printerIndex: int
    image: str  # base64 data URL

    @field_validator('printerIndex')
    @classmethod
    def non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError('printerIndex must be non-negative')
        return v


class ZplRawRequest(BaseModel):
    printerIndex: int
    zpl: str


class ZplPreviewRequest(BaseModel):
    printerIndex: int
    zpl: str


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title='Stikka-NG', docs_url=None, redoc_url=None)


# ── App info ─────────────────────────────────────────────────────────────────

@app.get('/api/appinfo')
async def api_appinfo() -> dict:
    return {
        'name': cfg.config.get('name', 'Stikka'),
        'subtitle': cfg.config.get('subtitle', ''),
        'zplExample': cfg.config.get('zpl_example', ''),
        'zplRawEnabled': cfg.config.get('zpl_raw_enabled', False),
    }


# ── Statistics ────────────────────────────────────────────────────────────────

@app.get('/api/stats')
async def api_stats() -> dict:
    return cfg.read_stats()


# ── README ────────────────────────────────────────────────────────────────────

_README_PATH = Path('README.md')

@app.get('/api/readme', response_class=PlainTextResponse)
async def api_readme() -> str:
    if _README_PATH.exists():
        return _README_PATH.read_text(encoding='utf-8')
    return '# Stikka-NG\n\nNo README found.'


# ── Printers ─────────────────────────────────────────────────────────────────

@app.get('/api/printers')
async def api_printers() -> list[dict]:
    result = []
    for idx, p in enumerate(cfg.config.get('printers', [])):
        label = p.get('label', {})
        result.append({
            'index': idx,
            'name': p.get('name', ''),
            'serial': p.get('serial', ''),
            'type': p.get('type', ''),
            'dpi': p.get('dpi', 300),
            'label': {
                'width': label.get('width', 0.0),
                'length': label.get('length', 0.0),
                'isRound': label.get('is_round', False),
                'verticalOffset': label.get('vertical_offset', 0.0),
                'cut': label.get('cut', True),
            },
        })
    return result


# ── Fonts ─────────────────────────────────────────────────────────────────────

@app.get('/api/fonts')
async def api_fonts() -> list[dict]:
    fonts_dir = Path(cfg.config.get('fonts_dir', 'fonts'))
    use_system = cfg.config.get('use_system_fonts', False)
    font_pairs = list_fonts(font_dir=fonts_dir, use_system_fonts=use_system)
    result = []
    for name, fs_path in font_pairs:
        p = Path(fs_path)
        try:
            # Convert filesystem path to a URL served under /fonts/
            rel = p.relative_to(fonts_dir)
            url_path = f'/fonts/{rel.as_posix()}'
        except ValueError:
            # System font outside fonts_dir — serve by filename only
            url_path = f'/fonts/{p.name}'
        result.append({'name': name, 'path': url_path})
    return result


# ── Print ─────────────────────────────────────────────────────────────────────

@app.post('/api/print')
async def api_print(body: PrintRequest) -> dict:
    """Accept a pre-rendered base64 PNG from the frontend and send to printer."""
    printer = _get_printer(body.printerIndex)
    try:
        img = _decode_image(body.image)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f'Invalid image: {exc}') from exc

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, _dispatch_print, img, printer, 'frontend')
    except Exception as exc:
        log.error(f'Print failed: {exc}')
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {'status': 'ok'}


# ── Raw ZPL ───────────────────────────────────────────────────────────────────

@app.post('/api/zpl/raw')
async def api_zpl_raw(body: ZplRawRequest) -> dict:
    printer = _get_printer(body.printerIndex)
    if printer.get('type') != 'zpl':
        raise HTTPException(status_code=400, detail='Selected printer is not a ZPL printer')

    host, port_str = printer['connection'].split(':')
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, pi.print_zpl, body.zpl, host, int(port_str))
    except Exception as exc:
        log.error(f'Raw ZPL send failed: {exc}')
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    cfg.record_print('zpl_raw')
    return {'status': 'ok'}


# ── ZPL preview ───────────────────────────────────────────────────────────────

@app.post('/api/zpl/preview')
async def api_zpl_preview(body: ZplPreviewRequest) -> StreamingResponse:
    printer = _get_printer(body.printerIndex)
    label = printer.get('label', {})
    width = label.get('width', 80.0)
    height = label.get('length', 80.0) or 80.0  # fallback for continuous
    dpi = printer.get('dpi', 300)

    loop = asyncio.get_event_loop()
    try:
        img: Image.Image = await loop.run_in_executor(
            None, pi.get_zpl_preview, body.zpl, width, height, dpi
        )
    except Exception as exc:
        log.error(f'ZPL preview failed: {exc}')
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    buf = BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return StreamingResponse(buf, media_type='image/png')


# ── Random images (cat / dog / dino proxy) ────────────────────────────────────

@app.get('/api/random/{kind}')
async def api_random_image(kind: str) -> StreamingResponse:
    from stikka_label_helper import get_cat, get_dog, get_dino

    _fetchers = {'cat': get_cat, 'dog': get_dog, 'dino': get_dino}
    fetcher = _fetchers.get(kind)
    if fetcher is None:
        raise HTTPException(status_code=400, detail=f'Unknown image kind: {kind!r}')

    loop = asyncio.get_event_loop()
    try:
        img: Image.Image = await loop.run_in_executor(None, fetcher)
    except Exception as exc:
        log.error(f'Random image fetch ({kind}) failed: {exc}')
        raise HTTPException(status_code=502, detail=f'Could not fetch {kind} image') from exc

    buf = BytesIO()
    img.convert('RGB').save(buf, format='JPEG', quality=85)
    buf.seek(0)
    return StreamingResponse(buf, media_type='image/jpeg')


# ── Config (admin) ────────────────────────────────────────────────────────────

@app.get('/api/config')
async def api_config_get(x_config_password: str = Header(default='')) -> Response:
    if not _check_password(x_config_password):
        raise HTTPException(status_code=403, detail='Wrong password')
    return Response(
        content=json.dumps(cfg.clean_config(), indent=4),
        media_type='application/json',
    )


@app.post('/api/config')
async def api_config_post(
    request: Request,
    x_config_password: str = Header(default=''),
) -> dict:
    if not _check_password(x_config_password):
        raise HTTPException(status_code=403, detail='Wrong password')
    try:
        new_config: dict = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail='Invalid JSON body') from exc
    if not isinstance(new_config, dict):
        raise HTTPException(status_code=400, detail='Config must be a JSON object')

    cfg.config.clear()
    cfg.config.update(new_config)
    cfg.write_config()
    _load_config()  # re-parse label format shorthands
    return {'status': 'ok'}


# ── Printer scan (admin) ──────────────────────────────────────────────────────

# ── Scanner data tables ────────────────────────────────────────────────────────

# Brother QL USB PIDs (VID = 0x04F9)  →  (display name, default label format)
_QL_PIDS: dict[int, tuple[str, str]] = {
    0x2015: ('Brother QL-500',       '62x0'),
    0x2016: ('Brother QL-550',       '62x0'),
    0x201B: ('Brother QL-650TD',     '62x0'),
    0x2020: ('Brother QL-1050',      '102x0'),
    0x2027: ('Brother QL-560',       '62x0'),
    0x2028: ('Brother QL-570',       '62x0'),
    0x2029: ('Brother QL-580N',      '62x0'),
    0x202A: ('Brother QL-1060N',     '102x0'),
    0x2042: ('Brother QL-700',       '62x0'),
    0x2043: ('Brother QL-710W',      '62x0'),
    0x2044: ('Brother QL-720NW',     '62x0'),
    0x209B: ('Brother QL-800',       '62x0'),
    0x209C: ('Brother QL-810W',      '62x0'),
    0x209D: ('Brother QL-820NWB',    '62x0'),
    0x20A7: ('Brother QL-1100',      '102x0'),
    0x20A8: ('Brother QL-1110NWB',   '102x0'),
    0x20AB: ('Brother QL-1115NWB',   '102x0'),
    0x20C0: ('Brother QL-600',       '62x0'),
}

# Seiko SLP USB PIDs (VID = 0x0619)  →  (display name, default label format)
_SLP_PIDS: dict[int, tuple[str, str]] = {
    0x0126: ('Seiko SLP-650',   '28x89'),
    0x0152: ('Seiko SLP-650SE', '28x89'),
    0x015A: ('Seiko SLP-740',   '36x89'),
    0x0160: ('Seiko SLP-450',   '28x89'),
    0x016A: ('Seiko SLP-620',   '28x54'),
}

# Zebra Technologies MAC OUI prefixes (lower-case, colon-separated)
_ZEBRA_OUIS: frozenset[str] = frozenset({
    '00:05:12', '00:07:4d', '00:15:70', '00:23:68',
    '00:a0:f8', '40:83:de', '48:8e:b7', '60:95:32',
    '74:93:a4', '78:b8:d6', '84:24:8d', '88:bc:ac',
    '90:75:de', '94:fb:29', 'c4:7d:cc', 'c4:bb:4c',
    'c8:1c:fe', 'fc:59:7a',
})

# ── USB scanner (sysfs) ────────────────────────────────────────────────────────

def _query_ql_media(vid: int, pid: int, serial: str) -> str:
    """Query a Brother QL printer for its currently loaded media via USB.

    Sends a status-request command and parses the 32-byte response.
    Returns a label-format string like '62x0' or '62x29', or '' on failure.
    """
    try:
        import usb.core
        import usb.util

        find_kwargs: dict = {'idVendor': vid, 'idProduct': pid}
        if serial:
            find_kwargs['serial_number'] = serial
        dev = usb.core.find(**find_kwargs)
        if dev is None:
            return ''

        detached = False
        try:
            if dev.is_kernel_driver_active(0):
                dev.detach_kernel_driver(0)
                detached = True
        except (usb.core.USBError, NotImplementedError):
            pass

        intf = None
        try:
            dev.set_configuration()
            cfg_obj = dev.get_active_configuration()
            intf = cfg_obj[(0, 0)]
            usb.util.claim_interface(dev, intf)

            ep_out = usb.util.find_descriptor(
                intf,
                custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT,
            )
            ep_in = usb.util.find_descriptor(
                intf,
                custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN,
            )
            if ep_out is None or ep_in is None:
                return ''

            # Brother QL status-request command: ESC i S
            ep_out.write(b'\x1b\x69\x53', timeout=1000)
            resp = bytes(ep_in.read(32, timeout=1000))

            # Response header byte must be 0x80
            if len(resp) < 18 or resp[0] != 0x80:
                return ''

            width_mm  = resp[10]  # tape/label width in mm
            media_type = resp[11]  # 0x0A = continuous, 0x0B = die-cut
            length_mm  = resp[17]  # label length in mm (0 for continuous)

            if media_type == 0x0A:
                return f'{width_mm}x0'
            if media_type == 0x0B:
                return f'{width_mm}x{length_mm}'
            return ''
        finally:
            if intf is not None:
                try:
                    usb.util.release_interface(dev, intf)
                except Exception:
                    pass
            usb.util.dispose_resources(dev)
            if detached:
                try:
                    dev.attach_kernel_driver(0)
                except (usb.core.USBError, NotImplementedError):
                    pass
    except Exception as exc:
        log.debug(f'QL media query failed: {exc}')
        return ''


def _scan_usb_sysfs() -> list[dict]:
    """Scan /sys/bus/usb/devices for Brother QL and Seiko SLP printers.

    Returns a list of scanned-printer dicts.  For QL printers the current
    label media is queried from the device; Seiko returns the default format.
    """
    sysfs = Path('/sys/bus/usb/devices')
    if not sysfs.exists():
        return []

    results: list[dict] = []
    for entry in sysfs.iterdir():
        dev_path = sysfs / entry.name
        try:
            vid = int((dev_path / 'idVendor').read_text().strip(), 16)
            pid = int((dev_path / 'idProduct').read_text().strip(), 16)
        except (FileNotFoundError, ValueError):
            continue

        serial = ''
        try:
            serial = (dev_path / 'serial').read_text().strip()
        except FileNotFoundError:
            pass

        if vid == 0x04F9:
            info = _QL_PIDS.get(pid)
            if info is None:
                continue
            name, default_fmt = info
            conn = f'usb://0x{vid:04x}:0x{pid:04x}'
            if serial:
                conn += f'/{serial}'
            label_fmt = _query_ql_media(vid, pid, serial) or default_fmt
            results.append({
                'name': name,
                'type': 'brother_ql',
                'connection': conn,
                'serial': serial,
                'dpi': 300,
                'backend': 'pyusb',
                'labelFormat': label_fmt,
            })

        elif vid == 0x0619:
            info = _SLP_PIDS.get(pid)
            if info is None:
                continue
            name, default_fmt = info
            conn = f'usb://0x{vid:04x}:0x{pid:04x}'
            if serial:
                conn += f'/{serial}'
            results.append({
                'name': name,
                'type': 'seiko_slp',
                'connection': conn,
                'serial': serial,
                'dpi': 300,
                'backend': 'pyusb',
                'labelFormat': default_fmt,
            })

    return results


# ── Network Zebra scanner ─────────────────────────────────────────────────────

def _read_arp() -> dict[str, str]:
    """Return IP → lower-case MAC from /proc/net/arp."""
    table: dict[str, str] = {}
    try:
        data = Path('/proc/net/arp').read_text()
        for line in data.splitlines()[1:]:
            fields = line.split()
            if len(fields) >= 4:
                table[fields[0]] = fields[3].lower()
    except Exception:
        pass
    return table


def _is_zebra_mac(mac: str) -> bool:
    return mac.lower()[:8] in _ZEBRA_OUIS


def _get_local_subnets() -> list[_ipaddress.IPv4Network]:
    """Return a list of local IPv4 networks from `ip -4 addr`."""
    subnets: list[_ipaddress.IPv4Network] = []
    try:
        out = subprocess.run(
            ['ip', '-4', 'addr'],
            capture_output=True, text=True, timeout=3,
        ).stdout
        for m in _re.finditer(r'inet (\d+\.\d+\.\d+\.\d+/\d+)', out):
            try:
                net = _ipaddress.IPv4Interface(m.group(1)).network
                if not net.is_loopback:
                    subnets.append(net)
            except ValueError:
                pass
    except Exception as exc:
        log.debug(f'Subnet discovery failed: {exc}')
    return subnets


def _probe_ip(ip: str, timeout: float = 0.5) -> tuple[bool, bool]:
    """Return (port80_open, port9100_open) for ip, probed concurrently."""
    def _check(port: int) -> bool:
        try:
            with _socket.create_connection((ip, port), timeout=timeout):
                return True
        except OSError:
            return False

    with _cf.ThreadPoolExecutor(max_workers=2) as ex:
        f80   = ex.submit(_check, 80)
        f9100 = ex.submit(_check, 9100)
        return f80.result(), f9100.result()


def _get_hostname(ip: str, port80_open: bool) -> str:
    """Try to resolve a hostname for ip via reverse DNS then HTTP page title."""
    try:
        return _socket.gethostbyaddr(ip)[0]
    except _socket.herror:
        pass

    if port80_open:
        try:
            with _socket.create_connection((ip, 80), timeout=1.5) as s:
                s.sendall(b'GET / HTTP/1.0\r\nHost: ' + ip.encode() + b'\r\n\r\n')
                data = s.recv(4096).decode('latin-1', errors='replace')
            m = _re.search(r'<title>([^<]{1,80})</title>', data, _re.IGNORECASE)
            if m:
                return m.group(1).strip()
        except Exception:
            pass

    return ''


def _scan_network_zebra() -> list[dict]:
    """Probe all local /24 subnets for Zebra printers on ports 80 and 9100.

    A host is included when port 9100 is open AND either:
      - its ARP MAC matches a known Zebra OUI, or
      - port 80 is also open (fallback when ARP is empty).
    """
    subnets = _get_local_subnets()
    if not subnets:
        return []

    # Collect candidate IPs (one /24 per local subnet, deduped).
    seen: set[str] = set()
    candidates: list[str] = []
    for net in subnets:
        # Cap scan to /24 to avoid huge ranges on wider networks.
        scan_net = net
        if net.prefixlen < 24:
            scan_net = _ipaddress.IPv4Network(
                f'{str(net.network_address).rsplit(".", 1)[0]}.0/24'
            )
        for host in scan_net.hosts():
            ip = str(host)
            if ip not in seen:
                seen.add(ip)
                candidates.append(ip)

    if not candidates:
        return []

    log.debug(f'Zebra scan: probing {len(candidates)} IPs for port 9100 …')

    # Phase 1: quick port-9100 probe (high concurrency, short timeout).
    def _quick_9100(ip: str) -> str | None:
        try:
            with _socket.create_connection((ip, 9100), timeout=0.4):
                return ip
        except OSError:
            return None

    port9100_open: list[str] = []
    with _cf.ThreadPoolExecutor(max_workers=64) as ex:
        for result in ex.map(_quick_9100, candidates):
            if result:
                port9100_open.append(result)

    if not port9100_open:
        return []

    # Phase 2: verify with port 80 + ARP + hostname (fewer hosts now).
    arp = _read_arp()
    printers: list[dict] = []

    for ip in port9100_open:
        mac = arp.get(ip, '')
        if mac and not _is_zebra_mac(mac):
            continue  # Port 9100 open but definitely not a Zebra MAC.

        port80_open, _ = _probe_ip(ip, timeout=0.8)

        # Require port 80 when we have no ARP confirmation.
        if not mac and not port80_open:
            continue

        hostname = _get_hostname(ip, port80_open)
        if hostname:
            display_name = f'Zebra – {hostname}'
        elif mac:
            display_name = f'Zebra – {mac.upper()}'
        else:
            display_name = f'Zebra – {ip}'

        printers.append({
            'name': display_name,
            'type': 'zpl',
            'connection': f'{ip}:9100',
            'serial': '',
            'dpi': 203,
            'backend': 'network',
            'labelFormat': '101x152',
        })

    return printers

@app.get('/api/printers/scan')
async def api_printers_scan(x_config_password: str = Header(default='')) -> list[dict]:
    if not _check_password(x_config_password):
        raise HTTPException(status_code=403, detail='Wrong password')

    loop = asyncio.get_event_loop()
    results: list[dict] = await loop.run_in_executor(None, _do_scan_printers)
    return results


def _do_scan_printers() -> list[dict]:
    """Discover connected printers (blocking; runs in executor).

    - Brother QL: USB only, name from PID table, label from device status query.
    - Seiko SLP: USB only, name and default format from PID table.
    - Zebra:     network scan across local /24 subnets; port 9100 + port 80
                 verified against known Zebra MAC OUIs.
    """
    results: list[dict] = []

    # USB: Brother QL + Seiko SLP
    try:
        results.extend(_scan_usb_sysfs())
    except Exception as exc:
        log.debug(f'USB sysfs scan failed: {exc}')

    # Network: Zebra / ZPL printers
    try:
        results.extend(_scan_network_zebra())
    except Exception as exc:
        log.debug(f'Network Zebra scan failed: {exc}')

    return results


# ── Static files (fonts + frontend SPA) ───────────────────────────────────────

def _mount_static(application: FastAPI) -> None:
    fonts_dir = cfg.config.get('fonts_dir', 'fonts')
    if Path(fonts_dir).exists():
        application.mount(
            '/fonts',
            StaticFiles(directory=fonts_dir),
            name='fonts',
        )
        log.info(f'Serving fonts from {fonts_dir!r}')

    frontend_dist = Path('frontend/dist')
    if frontend_dist.exists():
        # html=True serves index.html on 404 — SPA routing fallback
        application.mount(
            '/',
            StaticFiles(directory=str(frontend_dist), html=True),
            name='frontend',
        )
        log.info(f'Serving frontend from {frontend_dist}')
    else:
        log.warning(
            'frontend/dist not found. Run `npm run build` inside frontend/ '
            'to generate the production bundle.'
        )


# ---------------------------------------------------------------------------
# TLS helpers (mirror stikka.py logic)
# ---------------------------------------------------------------------------

def _ensure_self_signed_cert(cert_path: Path, key_path: Path) -> None:
    if cert_path.exists() and key_path.exists():
        return
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    log.info(f'Generating self-signed TLS certificate at {cert_path} …')
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    _load_config()
    cfg.init_stats_csv()
    _mount_static(app)

    host = cfg.config.get('host', '0.0.0.0')
    port = int(cfg.config.get('port', 8000))

    ssl_kwargs: dict = {}
    if cfg.config.get('ssl', False):
        cert_path = Path(cfg.config.get('ssl_certfile', 'certs/cert.pem'))
        key_path = Path(cfg.config.get('ssl_keyfile', 'certs/key.pem'))
        _ensure_self_signed_cert(cert_path, key_path)
        ssl_kwargs = {
            'ssl_certfile': str(cert_path),
            'ssl_keyfile': str(key_path),
        }
        log.info(f'HTTPS enabled (cert={cert_path}, key={key_path})')

    log.info(f"Stikka-NG server starting on {host}:{port}")
    uvicorn.run(app, host=host, port=port, **ssl_kwargs)

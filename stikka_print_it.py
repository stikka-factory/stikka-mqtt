"""
stikka_print_it.py
==================
Printer driver layer for Stikka-NG.

Covers:
- ZPL label generation and network printing (Zebra / compatible printers)
- ZPL live-preview via the Labelary REST API
- Brother QL raster printing via brother_ql
- Seiko SLP raw USB raster printing via pyusb

All functions obtain a shared logger from :mod:`stikka_label_helper`.
"""

from __future__ import annotations

import socket
from io import BytesIO

import requests
import zpl
from PIL import Image

from stikka_label_helper import log


# ---------------------------------------------------------------------------
# ZPL – Zebra / ZPL-compatible printers
# ---------------------------------------------------------------------------

def img_to_zpl(
    img: Image.Image,
    dpi: int = 300,
    label_width_mm: float = 80,
    label_length_mm: float = 80,
    vertical_offset_mm: float = 0,
) -> str:
    """Convert a PIL image to a ZPL label command string.

    Args:
        img: Source PIL image (RGB or RGBA).
        dpi: Printer resolution in dots per inch.
        label_width_mm: Label width in millimetres.
        label_length_mm: Label height in millimetres.
        vertical_offset_mm: Vertical origin offset in millimetres.

    Returns:
        ZPL command string ready to send to a printer.
    """
    log.debug(
        f'Converting image to ZPL: {img.size} px, '
        f'{label_width_mm}mm x {label_length_mm}mm @ {dpi} DPI'
    )
    dpmm = max(1, int(round(dpi / 25.4)))
    label = zpl.Label(label_length_mm, label_width_mm, dpmm)
    label.origin(0, vertical_offset_mm)
    label.write_graphic(img, label_width_mm)
    label.endorigin()
    zpl_data = label.dumpZPL()
    log.info(f'Generated ZPL data ({len(zpl_data)} bytes)')
    log.debug(f'ZPL data:\n{zpl_data}')
    return zpl_data


def get_zpl_preview(
    zpl_data: str,
    width: float,
    height: float,
    dpi: int = 300,
) -> Image.Image:
    """Render a ZPL string to an image via the Labelary REST API.

    Falls back to a blank white image if the API returns an error.

    Args:
        zpl_data: ZPL command string.
        width: Label width in millimetres.
        height: Label height in millimetres.
        dpi: Printer resolution (used to select Labelary density preset).

    Returns:
        PIL RGB image of the rendered label.
    """
    dpmm = max(1, int(round(dpi / 25.4)))
    url = (
        f'http://api.labelary.com/v1/printers/{dpmm}dpmm/labels/'
        f'{width / 25.4}x{height / 25.4}/0/'
    )
    response = requests.post(url, headers={}, files={'file': zpl_data}, stream=True)
    if response.status_code == 200:
        log.info(f'Received ZPL preview from Labelary API ({len(response.content)} bytes)')
        return Image.open(BytesIO(response.content))

    log.error(f'Labelary API error: {response.status_code} – {response.text}')
    width_px = int(round(width / 25.4 * dpi))
    height_px = int(round(height / 25.4 * dpi))
    return Image.new('RGB', (width_px, height_px), color='white')


def print_zpl(zpl_data: str, host: str = 'localhost', port: int = 9100) -> None:
    """Send a ZPL command string to a network printer via a raw TCP socket.

    Args:
        zpl_data: ZPL command string to transmit.
        host: Printer hostname or IP address.
        port: Raw printing port (default 9100).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    try:
        sock.connect((host, port))
        sock.sendall(zpl_data.encode('utf-8'))
        log.info(f'Sent ZPL data to printer at {host}:{port}')
    except Exception as exc:
        log.error(f'Error sending ZPL to {host}:{port}: {exc}')
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# Brother QL
# ---------------------------------------------------------------------------

def print_ql(
    img: Image.Image,
    identfier: str,
    backend_name: str,
    model: str,
    label_width_mm: float = 80,
    label_length_mm: float = 80,
    dpi: int = 300,
) -> None:
    """Print *img* on a Brother QL label printer using the brother_ql library.

    Args:
        img: PIL image to print.
        identfier: Printer identifier (USB path or network address) as
            understood by brother_ql.
        backend_name: Backend name for brother_ql (e.g. ``'pyusb'``).
        model: Printer model string (e.g. ``'QL-720NW'``).
        label_width_mm: Label width in millimetres.
        label_length_mm: Label height in millimetres (0 = continuous).
        dpi: Printer resolution.
    """
    from brother_ql.raster import BrotherQLRaster
    from brother_ql.conversion import convert
    from brother_ql.backends.helpers import send

    log.debug(f'Printing image on Brother QL printer: {img.size} pixels')
    media_name = (
        f'{label_width_mm}x{label_length_mm}' if label_length_mm != 0
        else f'{label_width_mm}'
    )
    qlr = BrotherQLRaster(model)
    instructions = convert(
        qlr=qlr,
        images=[img],
        label=media_name,
        rotate=0,
        threshold=50,
        compress=False,
        red=False,
        dpi_600=False,
        hq=True,
        cut=True,
    )
    success = send(
        instructions=instructions,
        printer_identifier=identfier,
        backend_identifier=backend_name,
    )
    if success:
        log.info(f'Print job sent to {identfier} via {backend_name}')
    else:
        log.error(f'Failed to send print job to {identfier} via {backend_name}')


# ---------------------------------------------------------------------------
# Seiko SLP – raw USB raster protocol
# ---------------------------------------------------------------------------

# SLP protocol command bytes
_SLP_CMD_PRINT    = 0x04   # uncompressed raster line: CMD len data...
_SLP_CMD_MARGIN   = 0x06   # set left margin in mm
_SLP_CMD_LINEFEED = 0x0A   # advance 1 blank line
_SLP_CMD_VERTTAB  = 0x0B   # advance N blank lines: CMD n
_SLP_CMD_FORMFEED = 0x0C   # eject / cut the label
_SLP_CMD_SETSPEED = 0x0D   # 0x00=draft, 0x02=fine (300 dpi models)
_SLP_CMD_DENSITY  = 0x0E   # print density
_SLP_MAX_DOTS     = 576    # SLP-650 hardware maximum dots per line


def _parse_seiko_connection(connection: str) -> tuple[int, int]:
    """Parse a ``usb://0xVVVV:0xPPPP`` connection string into ``(VID, PID)``.

    Args:
        connection: Connection string from the printer config, e.g.
            ``'usb://0x0619:0x0126'``.

    Returns:
        ``(vendor_id, product_id)`` as integers.
    """
    rest = connection.replace('usb://', '')
    vid_str, pid_str = rest.split(':')
    return int(vid_str, 16), int(pid_str, 16)


def _image_to_slp_rows(im: Image.Image) -> tuple[list[bytes], int]:
    """Convert a 1-bit PIL image to a list of SLP-protocol row byte strings.

    Pillow's mode ``'1'`` is packed MSB-first with 1=white.  The SLP protocol
    treats 1 as black, so each byte is inverted.  Padding bits in the last
    byte of each row (introduced when the image width is not a multiple of 8)
    are masked back to 0 (white) after inversion to avoid a black fringe.

    Args:
        im: 1-bit PIL image.

    Returns:
        ``(rows, bytes_per_row)`` where *rows* is a list of :class:`bytes`
        objects (one per image row) and *bytes_per_row* is their common length.
    """
    w, h = im.size
    bytes_per_row = (w + 7) // 8
    used_bits = w % 8
    last_byte_mask = (0xFF << (8 - used_bits)) & 0xFF if used_bits != 0 else 0xFF
    raw = im.tobytes()
    rows: list[bytes] = []
    for y in range(h):
        row = bytearray(raw[y * bytes_per_row:(y + 1) * bytes_per_row])
        row = bytearray(b ^ 0xFF for b in row)
        if used_bits != 0:
            row[-1] &= last_byte_mask
        rows.append(bytes(row))
    return rows, bytes_per_row


def _build_slp_job(rows: list[bytes], bytes_per_row: int, dpi: int) -> bytes:
    """Assemble a complete SLP raster print job from pre-converted row data.

    The job starts with setup commands (margin, density, speed), followed by
    raster rows with blank-line compression via ``LINEFEED`` / ``VERTTAB``,
    and ends with a ``FORMFEED`` to eject the label.

    Args:
        rows: Row byte strings from :func:`_image_to_slp_rows`.
        bytes_per_row: Number of bytes in each row.
        dpi: Printer resolution, used to compute the left-margin in mm.

    Returns:
        Raw bytes of the complete SLP print job.
    """
    buf = bytearray()

    # Centre the image on the print head
    margin_dots = _SLP_MAX_DOTS - (bytes_per_row * 8)
    margin_mm = max(0, int(12.7 * margin_dots / dpi))
    buf += bytes([_SLP_CMD_MARGIN, margin_mm])
    buf += bytes([_SLP_CMD_DENSITY, 0x00])   # 100 % density
    buf += bytes([_SLP_CMD_SETSPEED, 0x02])  # fine / 300 dpi mode

    blanks = 0
    for row in rows:
        if all(b == 0 for b in row):
            blanks += 1
        else:
            while blanks > 0:
                if blanks == 1:
                    buf += bytes([_SLP_CMD_LINEFEED])
                    blanks = 0
                elif blanks <= 255:
                    buf += bytes([_SLP_CMD_VERTTAB, blanks])
                    blanks = 0
                else:
                    buf += bytes([_SLP_CMD_VERTTAB, 255])
                    blanks -= 255

            row_data = bytearray(row)
            while len(row_data) > 1 and row_data[-1] == 0:
                row_data.pop()
            buf += bytes([_SLP_CMD_PRINT, len(row_data)]) + row_data

    buf += bytes([_SLP_CMD_FORMFEED])
    return bytes(buf)


def print_seiko(img: Image.Image, printer_config: dict) -> None:
    """Print *img* on a Seiko SLP printer via USB (pyusb).

    The image is converted to 1-bit with autocontrast + Floyd-Steinberg
    dithering, encoded into an SLP raster job, and sent to the printer in
    4 KiB chunks.  The USB interface is always released after the transfer
    (even on error) so subsequent prints succeed.

    Args:
        img: PIL image to print (any mode).
        printer_config: Printer configuration dict from ``config.json``.
            Must contain ``'connection'`` (``usb://0xVVVV:0xPPPP``),
            ``'dpi'``, and ``'name'``.

    Raises:
        RuntimeError: If the printer is not found on USB or no bulk-OUT
            endpoint is available.
    """
    import usb.core
    import usb.util
    from PIL import ImageOps

    dpi = printer_config.get('dpi', 300)
    connection = printer_config.get('connection', '')
    name = printer_config.get('name', 'Seiko SLP')
    log.debug(f"Preparing Seiko SLP print job for '{name}' at {dpi} DPI")

    vid, pid = _parse_seiko_connection(connection)

    mono = ImageOps.autocontrast(img.convert('L')).convert('1')
    rows, bpr = _image_to_slp_rows(mono)
    job = _build_slp_job(rows, bpr, dpi)
    log.debug(f'SLP job: {len(rows)} rows, {bpr} bytes/row, {len(job)} bytes total')

    dev = usb.core.find(idVendor=vid, idProduct=pid)
    if dev is None:
        raise RuntimeError(
            f'Seiko printer not found (VID={vid:#06x} PID={pid:#06x}). '
            'Check the cable and permissions.'
        )

    kernel_driver_detached = False
    try:
        try:
            if dev.is_kernel_driver_active(0):
                dev.detach_kernel_driver(0)
                kernel_driver_detached = True
        except (usb.core.USBError, NotImplementedError):
            pass

        dev.set_configuration()
        cfg = dev.get_active_configuration()
        intf = cfg[(0, 0)]
        usb.util.claim_interface(dev, intf)

        try:
            ep_out = usb.util.find_descriptor(
                intf,
                custom_match=lambda e:
                    usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT,
            )
            if ep_out is None:
                raise RuntimeError('No bulk-OUT endpoint found on the Seiko printer.')

            chunk = 4096
            for offset in range(0, len(job), chunk):
                ep_out.write(job[offset:offset + chunk])

            log.info(f"Sent {len(job)} bytes to '{name}'.")
        finally:
            usb.util.release_interface(dev, intf)
    finally:
        usb.util.dispose_resources(dev)
        if kernel_driver_detached:
            try:
                dev.attach_kernel_driver(0)
            except (usb.core.USBError, NotImplementedError):
                pass

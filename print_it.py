from PIL import Image
import requests
import zpl

from brother_ql.backends import backend_factory
from brother_ql.raster import BrotherQLRaster, BytesIO, ModelsManager
from brother_ql.conversion import convert
from brother_ql.backends.helpers import get_status, send, get_printer

import label_helper as h
import socket
log = h.log

# ---------------------------------------------------------------------------
# Seiko SLP protocol constants
# ---------------------------------------------------------------------------
_SLP_CMD_PRINT    = 0x04   # uncompressed raster line: CMD len data...
_SLP_CMD_MARGIN   = 0x06   # set left margin in mm
_SLP_CMD_LINEFEED = 0x0A   # advance 1 blank line
_SLP_CMD_VERTTAB  = 0x0B   # advance N blank lines: CMD n
_SLP_CMD_FORMFEED = 0x0C   # eject / cut the label
_SLP_CMD_SETSPEED = 0x0D   # 0x00=draft, 0x02=fine (300 dpi models)
_SLP_CMD_DENSITY  = 0x0E   # print density
_SLP_MAX_DOTS     = 576    # SLP-650 hardware maximum dots per line


def img_to_zpl(img, dpi=300, label_width_mm=80, label_length_mm=80,vertical_offset_mm=0):
    log.debug(f"Converting image to ZPL format: {img.size} pixels, label size {label_width_mm}mm x {label_length_mm}mm at {dpi} DPI")
    dpmm = max(1, int(round(dpi / 25.4)))
    l = zpl.Label(label_length_mm, label_width_mm, dpmm)
    l.origin(0, vertical_offset_mm)
    l.write_graphic(img,label_width_mm)
    l.endorigin()
    zpl_data = l.dumpZPL()
    log.info(f"Generated ZPL data ({len(zpl_data)} bytes)")
    log.debug(f"ZPL data:\n{zpl_data}")
    return zpl_data

def get_zpl_preview(zpl_data, width, height, dpi=300):
    dpmm = max(1, int(round(dpi / 25.4)))
    # adjust print density (8dpmm), label width (4 inches), label height (6 inches), and label index (0) as necessary
    url = f'http://api.labelary.com/v1/printers/{dpmm}dpmm/labels/{width/25.4}x{height/25.4}/0/'
    files = {'file' : zpl_data}
    response = requests.post(url, headers = {}, files = files, stream = True)
    if response.status_code == 200:
        log.info(f"Received ZPL preview image from Labelary API ({len(response.content)} bytes)")
        img = Image.open(BytesIO(response.content))
        return img
    else:
        log.error(f"Error from Labelary API: {response.status_code} - {response.text}")
        # Return a blank white image as fallback
        width_px = int(round(width / 25.4 * dpi))
        height_px = int(round(height / 25.4 * dpi))
        return Image.new('RGB', (width_px, height_px), color='white')

def print_zpl(zpl_data, host="localhost", port=9100):
    mysocket = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    mysocket.settimeout(5)
    try:
        mysocket.connect((host, port))
        mysocket.sendall(zpl_data.encode('utf-8'))
        log.info(f"Sent ZPL data to printer at {host}:{port}")
    except Exception as e:
        log.error(f"Error while sending ZPL data to printer at {host}:{port}: {e}")
    finally: 
        mysocket.close()
    return zpl_data

def print_ql(img, identfier, backend_name,  model, label_width_mm=80, label_length_mm=80, dpi=300):
    log.debug(f"Printing image on Brother QL printer: {img.size} pixels")
    media_name = f"{label_width_mm}x{label_length_mm}" if label_length_mm != 0 else f"{label_width_mm}"
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
        log.info(f"Print job sent successfully to printer {identfier} using backend {backend_name}")
    else:
        log.error(f"Failed to send print job to printer {identfier} using backend {backend_name}")


def send_to_zpl_printer(zpl: str, printer_config: dict):
    log.debug(f"Sending ZPL to printer {printer_config['name']}...")
    if printer_config['backend'] == 'file':
        with open('debug_output.zpl', 'w') as f:
            f.write(zpl)
        log.info(f"ZPL written to debug_output.zpl for printer {printer_config['name']}.")
    else:
        log.error(f"Unsupported printer backend: {printer_config['backend']} for printer {printer_config['name']}.")

def send_to_ql_printer(image, printer_config: dict):
    log.debug(f"Sending image to printer {printer_config['name']}...")
    if printer_config['backend'] == 'file':
        image.save('debug_output.png')
        log.info(f"Image saved as debug_output.png for printer {printer_config['name']}.")
    else:
        log.error(f"Unsupported printer backend: {printer_config['backend']} for printer {printer_config['name']}.")


# ---------------------------------------------------------------------------
# Seiko SLP printing
# ---------------------------------------------------------------------------

def _parse_seiko_connection(connection: str) -> tuple[int, int]:
    """Parse 'usb://0xVVVV:0xPPPP' into (VID, PID)."""
    rest = connection.replace('usb://', '')
    vid_str, pid_str = rest.split(':')
    return int(vid_str, 16), int(pid_str, 16)


def _image_to_slp_rows(im) -> tuple[list[bytes], int]:
    """
    Convert a 1-bit PIL image to a list of packed row bytes.
    Pillow mode '1': packed MSB-first, 1=white; SLP protocol: 1=black, so invert.
    """
    w, h = im.size
    bytes_per_row = (w + 7) // 8
    raw = im.tobytes()
    rows = []
    for y in range(h):
        row = bytearray(raw[y * bytes_per_row:(y + 1) * bytes_per_row])
        row = bytearray(b ^ 0xFF for b in row)
        rows.append(bytes(row))
    return rows, bytes_per_row


def _build_slp_job(rows: list[bytes], bytes_per_row: int, dpi: int) -> bytes:
    """Assemble a complete SLP raster print job."""
    buf = bytearray()

    # Centre the image: left margin = half of unused dots converted to mm
    margin_dots = _SLP_MAX_DOTS - (bytes_per_row * 8)
    margin_mm = int(12.7 * margin_dots / dpi)
    if margin_mm < 0:
        margin_mm = 0
    buf += bytes([_SLP_CMD_MARGIN, margin_mm])
    buf += bytes([_SLP_CMD_DENSITY, 0x00])   # 100% density
    buf += bytes([_SLP_CMD_SETSPEED, 0x02])  # fine / 300 dpi mode

    blanks = 0
    for row in rows:
        is_blank = all(b == 0 for b in row)
        if is_blank:
            blanks += 1
        else:
            # flush accumulated blank lines
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

            # strip trailing zero bytes to save bandwidth
            row_data = bytearray(row)
            while len(row_data) > 1 and row_data[-1] == 0:
                row_data.pop()
            buf += bytes([_SLP_CMD_PRINT, len(row_data)]) + row_data

    buf += bytes([_SLP_CMD_FORMFEED])
    return bytes(buf)


def print_seiko(img, printer_config: dict) -> None:
    """Print a PIL image on a Seiko SLP printer via USB (pyusb)."""
    import usb.core
    import usb.util
    from PIL import ImageOps

    dpi = printer_config.get('dpi', 300)
    connection = printer_config.get('connection', '')
    name = printer_config.get('name', 'Seiko SLP')
    log.debug(f"Preparing Seiko SLP print job for '{name}' at {dpi} DPI")

    vid, pid = _parse_seiko_connection(connection)

    # Convert to 1-bit with Floyd-Steinberg dithering
    mono = ImageOps.autocontrast(img.convert('L')).convert('1')

    rows, bpr = _image_to_slp_rows(mono)
    job = _build_slp_job(rows, bpr, dpi)
    log.debug(f"SLP job: {len(rows)} rows, {bpr} bytes/row, {len(job)} bytes total")

    dev = usb.core.find(idVendor=vid, idProduct=pid)
    if dev is None:
        raise RuntimeError(
            f"Seiko printer not found (VID={vid:#06x} PID={pid:#06x}). "
            "Check the cable and permissions."
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
                raise RuntimeError("No bulk-OUT endpoint found on the Seiko printer.")

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


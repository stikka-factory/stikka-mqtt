import zpl

from brother_ql.backends import backend_factory
from brother_ql.raster import BrotherQLRaster, ModelsManager
from brother_ql.conversion import convert
from brother_ql.backends.helpers import get_status, send, get_printer

import helpers as h
import socket
log = h.log


def img_to_zpl(img, dpi=300, label_width_mm=80, label_length_mm=80,vertical_offset_mm=0):
    log.debug(f"Converting image to ZPL format: {img.size} pixels, label size {label_width_mm}mm x {label_length_mm}mm at {dpi} DPI")
    dpmm = max(1, int(round(dpi / 25.4)))
    l = zpl.Label(label_length_mm, label_width_mm, dpmm)
    l.origin(0, vertical_offset_mm)
    l.write_graphic(img,label_width_mm)
    l.endorigin()
    zpl_data = l.dumpZPL()
    log.debug(f"Generated ZPL data ({len(zpl_data)} bytes):\n{zpl_data}")
    return zpl_data

def print_zpl(zpl_data, host="localhost", port=9100):
    log.debug(f"Generated ZPL data ({len(zpl_data)} bytes):\n{zpl_data}")
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



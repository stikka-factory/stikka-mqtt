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

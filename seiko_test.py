"""
Print a 1-bit raster image on a Seiko SLP-650 via USB (pyusb + Pillow).

Usage:
    python slp650_print.py image.png

Requirements:
    pip install pyusb pillow

On Linux you may need a udev rule or run as root.
On Windows you need libusb / WinUSB bound to the printer (e.g. via Zadig).
On macOS: brew install libusb

Protocol reference:
    https://github.com/danieloneill/SeikoSLPLinuxDriver
    https://github.com/michaelrsweet/lprint
"""

import sys
import usb.core
import usb.util
from PIL import Image, ImageOps

# ----- configuration --------------------------------------------------------
VID = 0x0619
PID = 0x0126
PRINTER_DPI = 300
LABEL_WIDTH_MM = 36             # label width in millimetres
MAX_DOTS_PER_LINE = 576         # SLP-650 hardware maximum
# -----------------------------------------------------------------------------

LABEL_WIDTH_DOTS = int(LABEL_WIDTH_MM / 25.4 * PRINTER_DPI)

# ----- SLP command bytes (from SeikoSLPCommands.h) ---------------------------
SLP_CMD_PRINT     = 0x04        # uncompressed raster line: CMD len data...
SLP_CMD_MARGIN    = 0x06        # set left margin in mm
SLP_CMD_LINEFEED  = 0x0A        # advance 1 blank line
SLP_CMD_VERTTAB   = 0x0B        # advance N blank lines: CMD n
SLP_CMD_FORMFEED  = 0x0C        # eject / cut the label
SLP_CMD_SETSPEED  = 0x0D        # 0x00=draft, 0x02=fine (300dpi models)
SLP_CMD_DENSITY   = 0x0E        # print density
# -----------------------------------------------------------------------------


def load_image(path: str, width: int) -> Image.Image:
    """Open an image, resize to label width, and convert to 1-bit."""
    im = Image.open(path).convert("RGB")
    im = ImageOps.autocontrast(ImageOps.grayscale(im))

    # scale to label width, keep aspect ratio
    w, h = im.size
    new_h = int(h * (width / w))
    im = im.resize((width, new_h), Image.LANCZOS)

    # Floyd-Steinberg dithering → 1-bit
    return im.convert("1")


def image_to_rows(im: Image.Image) -> tuple[list[bytes], int]:
    """
    Return (list-of-row-bytes, bytes_per_row) from a 1-bit image.
    In Pillow mode "1", a set bit (1) = white, 0 = black.
    The SLP protocol treats a set bit as black, so we invert.
    """
    w, h = im.size
    bytes_per_row = (w + 7) // 8
    raw = im.tobytes()  # packed 1-bit, MSB first

    rows = []
    for y in range(h):
        row = bytearray(raw[y * bytes_per_row:(y + 1) * bytes_per_row])
        # invert: Pillow 1=white, SLP 1=black
        row = bytearray(b ^ 0xFF for b in row)
        rows.append(bytes(row))
    return rows, bytes_per_row


def build_slp_job(rows: list[bytes], bytes_per_row: int) -> bytes:
    """
    Build a raw SLP-650 print job using the actual Seiko SLP protocol.

    Protocol (from the official CUPS driver & lprint):
      CMD_MARGIN  n          – set left margin (mm)
      CMD_DENSITY n          – set density (0-3)
      CMD_SETSPEED n         – 0x02 = fine/high quality
      For each raster line:
        if blank: CMD_LINEFEED (single) or CMD_VERTTAB n (multiple)
        if data:  CMD_PRINT len <len bytes of raster data>
      CMD_FORMFEED             – eject label
    """
    buf = bytearray()

    # --- set left margin (centre the image on the label head) ---
    margin_dots = MAX_DOTS_PER_LINE - (bytes_per_row * 8)
    margin_mm = int(12.7 * margin_dots / PRINTER_DPI)
    if margin_mm < 0:
        margin_mm = 0
    buf += bytes([SLP_CMD_MARGIN, margin_mm])

    # --- density: 0x00 = 100% (medium) ---
    buf += bytes([SLP_CMD_DENSITY, 0x00])

    # --- fine mode / high quality for 300dpi models ---
    buf += bytes([SLP_CMD_SETSPEED, 0x02])

    # --- raster data ---
    blanks = 0
    for row in rows:
        # check if row is all zeros (blank)
        is_blank = all(b == 0 for b in row)

        if is_blank:
            blanks += 1
        else:
            # flush accumulated blank lines
            while blanks > 0:
                if blanks == 1:
                    buf += bytes([SLP_CMD_LINEFEED])
                    blanks = 0
                elif blanks <= 255:
                    buf += bytes([SLP_CMD_VERTTAB, blanks])
                    blanks = 0
                else:
                    buf += bytes([SLP_CMD_VERTTAB, 255])
                    blanks -= 255

            # strip trailing zero bytes from row to save bandwidth
            row_data = bytearray(row)
            while len(row_data) > 1 and row_data[-1] == 0:
                row_data.pop()

            buf += bytes([SLP_CMD_PRINT, len(row_data)]) + row_data

    # --- eject label ---
    buf += bytes([SLP_CMD_FORMFEED])

    return bytes(buf)


def usb_send(data: bytes) -> None:
    """Find the SLP-650 on USB and send raw data to its bulk-OUT endpoint."""
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        raise SystemExit(
            f"Printer not found (VID={VID:#06x} PID={PID:#06x}). "
            "Check the cable and permissions."
        )

    # detach kernel driver if active (Linux)
    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
    except (usb.core.USBError, NotImplementedError):
        pass

    dev.set_configuration()
    cfg = dev.get_active_configuration()
    intf = cfg[(0, 0)]

    ep_out = usb.util.find_descriptor(
        intf,
        custom_match=lambda e:
            usb.util.endpoint_direction(e.bEndpointAddress)
            == usb.util.ENDPOINT_OUT,
    )
    if ep_out is None:
        raise SystemExit("No bulk-OUT endpoint found on the printer.")

    # send in chunks
    CHUNK = 4096
    for offset in range(0, len(data), CHUNK):
        ep_out.write(data[offset:offset + CHUNK])

    print(f"Sent {len(data)} bytes to the printer.")


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python slp650_print.py <image-file>")

    print(f"Label: {LABEL_WIDTH_MM} mm -> {LABEL_WIDTH_DOTS} dots @ {PRINTER_DPI} dpi")

    im = load_image(sys.argv[1], LABEL_WIDTH_DOTS)
    rows, bpr = image_to_rows(im)

    print(f"Image: {im.size[0]}x{im.size[1]} px, {bpr} bytes/row")

    job = build_slp_job(rows, bpr)
    usb_send(job)
    print("Done!")


if __name__ == "__main__":
    main()
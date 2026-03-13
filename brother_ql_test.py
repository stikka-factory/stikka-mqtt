from dataclasses import dataclass
from brother_ql.backends import backend_factory
from brother_ql import labels
from brother_ql.raster import BrotherQLRaster
from brother_ql.conversion import convert
from brother_ql.backends.helpers import get_status, send, get_printer
import usb.core


class BrotherPrinter:
    identifier: str
    serial_number: str
    backend: dict
    backend_name: str
    model: str
    status_type: str
    phase_type: str
    media_width: str
    media_length: str
    media_type: str

    def __init__(self, identifier, serial_number, backend, backend_name="pyusb"):
        self.identifier = identifier
        self.serial_number = serial_number
        self.backend = backend
        self.backend_name = backend_name
        self.update_status()

    def update_status(self):
        printer = get_printer(self.identifier, self.backend_name)
        status = get_status(printer)
        print(f"Status for printer {self.serial_number}: {status}")
        self.model = status.get("model", "Unknown")
        self.status_type = status.get("status_type", "Unknown")
        self.media_width = status.get("media_width", "Unknown")
        self.phase_type = status.get("phase_type", "Unknown")
        self.media_length = status.get("media_length", "Unknown")
        self.media_type = status.get("media_type", "Unknown")

    def print_image(self,img):
        qlr = BrotherQLRaster(self.model)
        instructions = convert(
            qlr=qlr,
            images=[img],
            label="50",
            rotate=0,
            threshold=70,
            compress=True,
            red=False,
            dpi_600=False,
            hq=True,
            cut=True,
        )
        success = send(
            instructions=instructions,
            printer_identifier=self.identifier,
            backend_identifier=self.backend_name,
        )
        
        if not success:
            print(f"Failed to send print job to printer {self.serial_number}")



    def __str__(self):
        return f"BrotherPrinter\n\tidentifier:\t\t{self.identifier}\n\tserial_number:\t{self.serial_number}\n\tmodel:\t\t{self.model}\n\tstatus_type:\t{self.status_type}\n\tmedia_width:\t{self.media_width}\n\tphase_type:\t{self.phase_type}\n\tmedia_length:\t{self.media_length}\n\tmedia_type:\t{self.media_type}"


def find_brother_ql(backend_name="pyusb"):
    """Find Brother QL printers using the specified backend."""
    ql_printers = {}
    backend = backend_factory(backend_name)
    print(f"Searching for Brother QL printers using {backend_name} backend...")

    available_devices = backend["list_available_devices"]()
    for printer in available_devices:
        identifier = printer["identifier"]
        parts = identifier.split("/")
        if len(parts) < 4:
            print(
                f"Skipping device with invalid identifier format: {identifier}")
            continue

        serial_number = parts[3]
        pr = BrotherPrinter(identifier, serial_number, backend, backend_name)
        ql_printers[serial_number] = pr
        print(f"Found printer: {pr}")
    return ql_printers


if __name__ == "__main__":
    from label import StikkaLabel, TextElement, ImageElement, BarcodeElement

    printers = find_brother_ql("pyusb")

    for serial, printer in printers.items():
        label = StikkaLabel(50, 20)
        label.add_text("Hello, World!", x=0, y=10, char_height=4, char_width=4, line_width=50, justification='L', font='arial.ttf')
        label.add_text("Hello, World!", x=10, y=30, char_height=10, char_width=4, line_width=50, justification='C', font='arial.ttf')
        printer.print_image(label.render_image())
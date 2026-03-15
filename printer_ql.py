from labelprinter import LabelPrinter

import logger
log = logger.log

# imports for Brother QL printer
from brother_ql.backends import backend_factory
from brother_ql.raster import BrotherQLRaster, ModelsManager
from brother_ql.conversion import convert
from brother_ql.backends.helpers import get_status, send, get_printer
from dataclasses import dataclass
from PIL import Image



@dataclass
class BrotherPrintJob:
    img: Image
    rotate: int =0
    threshold: int = 70
    compress: bool = True
    red: bool = False
    dpi_600: bool = False
    hq: bool = True
    cut: bool =  True

@dataclass
class BrotherPrinterStatus:
    series_code: int = 52
    model_code: int = 71
    model: str = "QL-600" 
    status_type: str = "Reply to status request"
    status_code: int = 0
    phase_type: str = "Waiting to receive"
    media_type: str = "Continuous length tape"
    media_category: str = "DK"
    tape_color: str = ""
    text_color: str = ""
    media_width: int = 62
    media_length: int = 0
    media_name: str = "62"
    setting: str = None
    errors: list = None 

class BrotherPrinter(LabelPrinter):
    identifier: str
    serial_number: str
    backend: dict
    backend_name: str
    model: str
    status: BrotherPrinterStatus
    print_queue: list

    def __init__(self, identifier, serial_number, backend, backend_name="pyusb",):
        self.identifier = identifier
        self.serial_number = serial_number
        self.backend = backend
        self.backend_name = backend_name
        self.model = self._get_model_from_identifier(identifier)
        self.update_status()
        self.print_queue = []

    def _get_model_from_identifier(self, identifier):
        model_manager = ModelsManager()
        try:
            product_id = identifier.split("/")[2].split(":")[1]
        except ValueError:
            log.error(f"Invalid device info format: {identifier}")
            return "Unknown"

        try:
            product_id_int = int(product_id, 16)
            for m in model_manager.iter_elements():
                if m.product_id == product_id_int:
                    log.info(f"Matched printer model: {m.identifier}")
                    return m.identifier

        except ValueError:
            log.error(f"Invalid product ID format: {product_id}")
            return "Unknown"

    def update_status(self):
        printer = get_printer(self.identifier, self.backend_name)
        try:
            status = get_status(printer)
            self.status = BrotherPrinterStatus(**status)
            self.status.media_name = f"{self.status.media_width}x{self.status.media_length}" if self.status.media_length != 0 else f"{self.status.media_width}"
            log.info(f"Updated status for printer {self.serial_number}: {self.status}")
        except Exception as e:
            log.warning(f"Failed to get status for printer {SN_output}: {e}")
            self.status = BrotherPrinterStatus()

    def add_to_queue(self, item:BrotherPrintJob):
        self.print_queue.append(item)
        log.info(f"Added item to print queue for printer {self.serial_number} . Queue length: {len(self.print_queue)}")

    def handle_queue(self):
            if len(self.print_queue) > 0:
                item = self.print_queue.pop(0)
                log.info(f"Processing print job for printer {self.serial_number}. Remaining queue length: {len(self.print_queue)}")
                self._print(item)

    def _print(self, item:BrotherPrintJob):
        qlr = BrotherQLRaster(self.model)
        instructions = convert(
            qlr=qlr,
            images=[item.img],
            label=self.status.media_name,
            rotate=item.rotate,
            threshold=item.threshold,
            compress=item.compress,
            red=item.red,
            dpi_600=item.dpi_600,
            hq=item.hq,
            cut=item.cut,
        )
        success = send(
            instructions=instructions,
            printer_identifier=self.identifier,
            backend_identifier=self.backend_name,
        )
        if not success:
            print(f"Failed to send print job to printer [bold magenta] {self.serial_number} [/bold magenta] ")
        if success:
            self.handle_queue()

    def __str__(self):
        return f'''Brother Printer: {self.serial_number}
\tidentifier:\t{self.identifier}
\tserial_number:\t{self.serial_number}
\tmodel:\t\t{self.model}
\tstatus_type:\t{self.status.status_type}
\tphase_type:\t{self.status.phase_type}
\tmedia_type:\t{self.status.media_type}
\tmedia_width:\t{self.status.media_width}
\tmedia_length:\t{self.status.media_length}
\tlabel_name:\t{self.status.media_name}'''


    @staticmethod
    def find(backend_name="pyusb"):
        """Find Brother QL printers using the specified backend."""
        ql_printers = {}
        backend = backend_factory(backend_name)
        log.info(f"Searching for Brother QL printers using {backend_name} backend...")

        available_devices = backend["list_available_devices"]()
        log.info(f"{len(available_devices)} Brother QL printer found on {backend_name}")
        for printer in available_devices:
            identifier = printer["identifier"]
            parts = identifier.split("/")
            if len(parts) < 4:
                log.warning(f"Skipping device with invalid identifier format: {identifier}")
                continue

            serial_number = parts[3]
            pr = BrotherPrinter(identifier, serial_number, backend, backend_name)
            ql_printers[serial_number] = pr
            log.debug(f"Found printer: {pr}")
        return ql_printers

from printer_abstract import LabelPrinter

import logger
log = logger.log

# imports for Brother QL printer
from brother_ql.backends import backend_factory
from brother_ql.raster import BrotherQLRaster, ModelsManager
from brother_ql.conversion import convert
from brother_ql.backends.helpers import get_status, send, get_printer
from dataclasses import dataclass
from PIL import Image
from label import StikkaLabel

@dataclass
class BrotherPrintJob:
    label: StikkaLabel
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

    def __repr__(self):
        return f'''\n[rgb(175,0,255)]Brother Printer Status:[/rgb(175,0,255)]
\tseries_code:\t{self.series_code}
\tmodel_code:\t{self.model_code}
\tmodel:\t\t{self.model}
\tstatus_type:\t{self.status_type}
\tstatus_code:\t{self.status_code}
\tphase_type:\t{self.phase_type}
\tmedia_type:\t{self.media_type}
\tmedia_category:\t{self.media_category}
\ttape_color:\t{self.tape_color}
\ttext_color:\t{self.text_color}
\tmedia_width:\t{self.media_width}
\tmedia_length:\t{self.media_length}
\tmedia_name:\t{self.media_name}
\tsetting:\t{self.setting}
\terrors:\t\t{self.errors}'''

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
                    log.info(f"Matched printer model: [magenta]{m.identifier}[/magenta]")
                    return m.identifier

        except ValueError:
            log.error(f"Invalid product ID format: {product_id}")
            return "Unknown"

    def update_status(self):
        printer = get_printer(self.identifier, self.backend_name)
        for attempt in range(2):
            try:
                status = get_status(printer)
                self.status = BrotherPrinterStatus(**status)
                self.status.media_name = f"{self.status.media_width}x{self.status.media_length}" if self.status.media_length != 0 else f"{self.status.media_width}"
                log.info(f"Updated status for printer [bold magenta]{self.serial_number}[/bold magenta]: {self.status}")
                break
            except Exception as e:
                log.warning(f"Failed to get status for printer [bold magenta]{self.serial_number}[/bold magenta]: {e}")
                self.status = BrotherPrinterStatus()

    def add_to_queue(self, item:BrotherPrintJob):
        self.print_queue.append(item)
        log.info(f"Added item to print queue for printer [bold magenta]{self.serial_number}[/bold magenta]. Queue length: {len(self.print_queue)}")

    def _handle_queue(self):
            if len(self.print_queue) > 0:
                item = self.print_queue.pop(0)
                log.info(f"Processing print job for printer [bold magenta]{self.serial_number}[/bold magenta]. Remaining queue length: {len(self.print_queue)}")
                self._print(item)

    def _print(self, item:BrotherPrintJob):
        qlr = BrotherQLRaster(self.model)
        instructions = convert(
            qlr=qlr,
            images=[item.label.render_image()],
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
            log.error(f"Failed to send print job to printer [bold magenta]{self.serial_number}[/bold magenta]")
        if success:
            log.info(f"Print job sent successfully to printer [bold magenta]{self.serial_number}[/bold magenta]")


    def __repr__(self):
        return f'''\n[rgb(175,0,255)] Brother Printer:[/rgb(175,0,255)] [bold magenta]{self.serial_number}[/bold magenta]
\tidentifier:\t{self.identifier}
\tserial_number:\t{self.serial_number}
\tmodel:\t\t{self.model}
\tbackend:\t{self.backend_name}
'''

    @staticmethod
    def find(backend_name="pyusb"):
        """Find Brother QL printers using the specified backend."""
        ql_printers = {}
        backend = backend_factory(backend_name)
        log.info(f"Searching for Brother QL printers using {backend_name} backend...")

        available_devices = backend["list_available_devices"]()
        log.info(f"{len(available_devices)} Brother QL printer [bold green]found[/bold green] on {backend_name}")
        for printer in available_devices:
            identifier = printer["identifier"]
            parts = identifier.split("/")
            if len(parts) < 4:
                log.warning(f"Skipping device with invalid identifier format: {identifier}")
                continue

            serial_number = parts[3]
            pr = BrotherPrinter(identifier, serial_number, backend, backend_name)
            log.info(f"Found printer: {pr}")
            ql_printers[serial_number] = pr
        return ql_printers
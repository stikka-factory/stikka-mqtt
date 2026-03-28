from printer_abstract import LabelPrinter
from dataclasses import dataclass
from label import StikkaLabel
import socket

import logger
import json
log = logger.log


@dataclass
class ZPLPrintJob:
    label: StikkaLabel
    bitmap_fonts: bool = True


@dataclass
class ZPLPrinterStatus:
    media_width: int = 70
    media_length: int = 50
    dpi: int = 203
    available: bool = True


class ZPLPrinter(LabelPrinter):
    identifier: str
    serial_number: str
    backend: dict
    backend_name: str
    model: str
    status: ZPLPrinterStatus


    def __init__(self, identifier, serial_number, backend, model,backend_name="ethernet",):
        self.identifier = identifier
        self.serial_number = serial_number
        self.backend = backend
        self.backend_name = backend_name
        self.model = model
        self.status = ZPLPrinterStatus()

    def _resolve_endpoint(self):
        host = None
        port = None

        if isinstance(self.backend, dict):
            host = self.backend.get("host") or self.backend.get("ip")
            port = self.backend.get("port")

        identifier = (self.identifier or "").strip()
        if identifier and ":" in identifier and (host is None or port is None):
            id_host, id_port = identifier.rsplit(":", 1)
            host = host or id_host
            port = port or id_port

        if host is None or port is None:
            raise ValueError(
                f"Invalid ZPL endpoint for printer {self.serial_number}: identifier='{self.identifier}', backend='{self.backend}'"
            )

        return str(host), int(port)

    def _print(self, item:ZPLPrintJob):
        log.info(f"Printing label on ZPL printer {self.model} with identifier {self.identifier} and  {self.status.dpi} DPI")
        host, port = self._resolve_endpoint()
        mysocket = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        mysocket.settimeout(5)
        try:           
            mysocket.connect((host, port)) #connecting to host
            mysocket.sendall(item.label.render_zpl(bitmap_font=item.bitmap_fonts).encode()) #sending ZPL command
        except Exception as e:
            log.error(f"Error with the connection: {e}")
        finally:
            mysocket.close() #closing connection

    def _handle_queue(self):
        log.debug(f"Queue handling not implemented for ZPL printer")

    def update_status(self):
        log.debug(f"Status update not completely implemented for ZPL printer")
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        try:
            host, port = self._resolve_endpoint()
            s.connect((host, port))
            s.shutdown(1)
            self.status.available = True
        except Exception:
            self.status.available = False
        finally:
            s.close()

    def add_to_queue(self, item:ZPLPrintJob):
        log.debug(f"Queue management not implemented for ZPL printer - sending directly to print")
        self._print(item)

    def __repr__(self):
        return f"ZPLPrinter(model={self.model}, identifier={self.identifier})"

    @staticmethod
    def find():
        # Placeholder for discovery logic, e.g., scanning network for printers
        log.info("Discovering ZPL printers...")
        try:
            log.info("Loading printer configurations from printers_config.json")
            with open('printers_config.json', 'r') as f:
                config = json.load(f)
            
            printers = []
            for printer_config in config.get("printers", []):
                print(printer_config)
                if printer_config.get("type") == "zpl":
                    printer = ZPLPrinter(
                        identifier=printer_config.get("identifier"),
                        serial_number=printer_config.get("serial_number"),
                        backend=printer_config.get("backend"),
                        model=printer_config.get("model"),
                        backend_name=printer_config.get("backend_name", "ethernet")
                    )
                    status = printer_config.get("status", {})
                    printer.status.dpi = status.get("dpi", 203)
                    printer.status.media_length = status.get("media_length", 50)
                    printer.status.media_width = status.get("media_width", 70)

                    printers.append(printer)
                   
            log.info(f"Found {len(printers)} ZPL printers")
            return printers
        except FileNotFoundError:
            log.error("printers_config.json not found")
            return []
        except json.JSONDecodeError as e:
            log.error(f"Error parsing printers_config.json: {e}")
            return []
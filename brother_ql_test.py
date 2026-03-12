import subprocess
import tempfile
import time
from brother_ql.models import ModelsManager
from brother_ql.backends import backend_factory
from brother_ql import labels
from brother_ql.raster import BrotherQLRaster
from brother_ql.conversion import convert
from brother_ql.backends.helpers import send
import usb.core


def find_and_parse_printer():
    """Find and parse Brother QL printer information."""
    model_manager = ModelsManager()
    
    print("Searching for Brother QL printer...")

    for backend_name in ["pyusb", "linux_kernel"]:
        try:
            print(f"Trying backend: {backend_name}")
            backend = backend_factory(backend_name)
            available_devices = backend["list_available_devices"]()
            print(f"Found {len(available_devices)} devices with {backend_name} backend")
            
            for printer in available_devices:
                print(f"Found device: {printer}")
                identifier = printer["identifier"]
                parts = identifier.split("/")

                if len(parts) < 4:
                    print(f"Skipping device with invalid identifier format: {identifier}")
                    continue

                protocol = parts[0]
                device_info = parts[2]
                serial_number = parts[3]
                
                try:
                    vendor_id, product_id = device_info.split(":")
                except ValueError:
                    print(f"Invalid device info format: {device_info}")
                    continue

                model = "QL-570"
                
                try:
                    product_id_int = int(product_id, 16)
                    for m in model_manager.iter_elements():
                        if m.product_id == product_id_int:
                            model = m.identifier
                            break
                    print(f"Matched printer model: {model}")
                except ValueError:
                    print(f"Invalid product ID format: {product_id}")
                    continue

                printer_info = {
                    "identifier": identifier,
                    "backend": backend_name,
                    "model": model,
                    "protocol": protocol,
                    "vendor_id": vendor_id,
                    "product_id": product_id,
                    "serial_number": serial_number,
                }
                print(f"Found printer: {printer_info}")
                return printer_info
                
        except Exception as e:
            print(f"Error with backend {backend_name}: {str(e)}")
            continue

    print("No Brother QL printer found")
    return None

if __name__ == "__main__":
    printer_info = find_and_parse_printer()
    if printer_info:
        print(f"Successfully found printer: {printer_info}")
    else:
        print("No printer found.")
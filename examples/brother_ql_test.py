#!/usr/bin/env python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from label.label import StikkaLabel
from labelprinter.printer_ql import BrotherPrintJob, BrotherPrinter
from webui.registry import PrinterRegistry
import time

registry = PrinterRegistry()
printers = registry.discover(BrotherPrinter.find)
time.sleep(2)

for serial, printer in printers.items():
    printer.check_queue()
    for i in range(3):
        label = StikkaLabel.test_label(printer.status.media_width, 70)

        l = label.render_image(framing=True)
        print_job= BrotherPrintJob(l)
        printer.add_to_queue(print_job) 

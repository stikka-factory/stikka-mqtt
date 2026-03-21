#!/usr/bin/env python

from label import StikkaLabel
from printer_ql import BrotherPrintJob, BrotherPrinter
from printer_registry import PrinterRegistry
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

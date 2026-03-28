#!/usr/bin/env python

from label import StikkaLabel
from printer_zpl import ZPLPrintJob, ZPLPrinter

printers  = ZPLPrinter.find()
print(f"Found {len(printers)} ZPL printers:")

for serial, printer in enumerate(printers):
    print(f"Printer {serial + 1}: {printer.model} (Identifier: {printer.identifier})")
    for i in range(2):
        label = StikkaLabel.test_label(100, 70)
        print_job= ZPLPrintJob(label)
        printer.add_to_queue(print_job)

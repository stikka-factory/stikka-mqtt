#!/usr/bin/env python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from label.label import StikkaLabel
from labelprinter.printer_zpl import ZPLPrintJob, ZPLPrinter

printers  = ZPLPrinter.find()
print(f"Found {len(printers)} ZPL printers:")

for serial, printer in enumerate(printers):
    print(f"Printer {serial + 1}: {printer.model} (Identifier: {printer.identifier})")
    for i in range(2):
        label = StikkaLabel.test_label(70, 50)
        print_job= ZPLPrintJob(label)
        printer.add_to_queue(print_job)

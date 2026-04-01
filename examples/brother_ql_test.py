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
    printer.check_queue()  # Start the queue checking loop with a 5-second interval
    for i in range(2):
        label = StikkaLabel(width=printer.status.media_width, height=15)
        label.add_text(f"Test {i+1}", x=5, y=1, char_height=10, char_width=1.0, line_width=80, font="fonts/Friez-Five.ttf")

        l = label
        print_job= BrotherPrintJob(l)
        printer.add_to_queue(print_job) 

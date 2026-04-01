#!/usr/bin/env python
"""Simplified test to check if both printers can print."""
import sys
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).parent.parent))

from label.label import StikkaLabel
from labelprinter.printer_ql import BrotherPrintJob, BrotherPrinter
from webui.registry import PrinterRegistry
import logger

log = logger.log

registry = PrinterRegistry()
printers = registry.discover(BrotherPrinter.find)

log.info(f"Found {len(printers)} printers")
for serial, printer in printers.items():
    log.info(f"Printer {serial}: width={printer.status.media_width}mm")

# Create a job for each printer
log.info("\n--- Creating and processing jobs ---")
for serial, printer in printers.items():
    log.info(f"\nAdding job to printer {serial}...")
    label = StikkaLabel(width=printer.status.media_width, height=15)
    label.add_text(f"Test-{serial}", x=5, y=1, char_height=10, char_width=1.0, line_width=80, font="fonts/Friez-Five.ttf")
    
    job = BrotherPrintJob(label)
    printer.add_to_queue(job)
    
    # Process immediately
    log.info(f"Processing queue for {serial}...")
    printer._handle_queue()
    time.sleep(1)

log.info("\n--- Done ---")

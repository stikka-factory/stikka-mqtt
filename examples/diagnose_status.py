#!/usr/bin/env python
"""Diagnose printer status to check if they're updating independently."""
import sys
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).parent.parent))

from labelprinter.printer_ql import BrotherPrinter
from webui.registry import PrinterRegistry
import logger

log = logger.log

def diagnose():
    """Show individual printer status updates."""
    registry = PrinterRegistry()
    printers = registry.discover(BrotherPrinter.find)
    
    log.info(f"Registry discovered {len(printers)} printers:")
    for serial, printer in printers.items():
        log.info(f"\nPrinter {serial}:")
        log.info(f"  Model: {printer.model}")
        log.info(f"  Media Width: {printer.status.media_width}")
        log.info(f"  Media Length: {printer.status.media_length}")
        log.info(f"  Status object id: {id(printer.status)}")
    
    # Check if status objects are same
    all_printers = list(printers.values())
    if len(all_printers) >= 2:
        log.warning(f"Status objects have same id? {id(all_printers[0].status) == id(all_printers[1].status)}")
        if id(all_printers[0].status) == id(all_printers[1].status):
            log.error("PROBLEM: Both printers share the same status object!")

if __name__ == "__main__":
    diagnose()

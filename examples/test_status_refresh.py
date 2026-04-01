#!/usr/bin/env python
"""Test multi-call status updates to see if media widths change."""
import sys
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).parent.parent))

from labelprinter.printer_ql import BrotherPrinter
import logger

log = logger.log

def diagnose():
    """Test status refresh for each printer."""
    found = BrotherPrinter.find()
    
    log.info(f"Found {len(found)} printers initially:")
    for serial, printer in found.items():
        log.info(f"  {serial}: {printer.status.media_width}mm")
    
    log.info("\n--- Refreshing status again for each printer ---")
    for serial, printer in found.items():
        log.info(f"\nCalling update_status() on {serial}...")
        printer.update_status()
        log.info(f"After update: {printer.status.media_width}mm")
        log.info(f"Full status: {printer.status}")

if __name__ == "__main__":
    diagnose()

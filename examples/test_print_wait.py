#!/usr/bin/env python
"""Test that properly waits for both printers to process jobs."""
import sys
from pathlib import Path
import time
import threading

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

# Create a job for each printer and start queue processing
log.info("\n--- Adding jobs and starting queue processing ---")
queue_threads = []
for serial, printer in printers.items():
    log.info(f"\nAdding job to printer {serial}...")
    label = StikkaLabel(width=printer.status.media_width, height=15)
    label.add_text(f"Test-{serial}", x=5, y=1, char_height=10, char_width=1.0, line_width=80, font="fonts/Friez-Five.ttf")
    
    job = BrotherPrintJob(label)
    printer.add_to_queue(job)
    log.info(f"Queue length for {serial}: {len(printer.print_queue)}")
    
    # Start queue processing
    log.info(f"Starting queue processing for {serial}...")
    printer.check_queue(interval=1)
    queue_threads.append((serial, printer))

# Wait for queues to empty (with timeout)
log.info("\n--- Waiting for jobs to process ---")
wait_time = 0
max_wait = 30  # 30 seconds max

while wait_time < max_wait:
    all_empty = True
    for serial, printer in queue_threads:
        queue_len = len(printer.print_queue)
        if queue_len > 0:
            all_empty = False
            log.info(f"[{wait_time}s] Printer {serial} queue length: {queue_len}")
    
    if all_empty:
        log.info("All queues empty!")
        break
    
    time.sleep(2)
    wait_time += 2

log.info(f"\n--- Done (waited {wait_time}s) ---")

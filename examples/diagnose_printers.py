#!/usr/bin/env python
"""Diagnose printer discovery to understand serial extraction."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from brother_ql.backends import backend_factory
import logger

log = logger.log

def diagnose():
    """Show raw device information and serial extraction."""
    backend = backend_factory("pyusb")
    available_devices = backend["list_available_devices"]()
    
    log.info(f"Found {len(available_devices)} Brother QL printers")
    
    for i, device in enumerate(available_devices):
        identifier = device.get("identifier", "UNKNOWN")
        log.info(f"\nDevice {i+1}:")
        log.info(f"  Full identifier: {identifier}")
        log.info(f"  Device dict: {device}")
        
        # Show extraction
        parts = identifier.split("/")
        log.info(f"  Split parts: {parts}")
        for j, part in enumerate(parts):
            log.info(f"    [{j}] = {part}")
        
        if len(parts) >= 4:
            serial = parts[3]
            log.info(f"  Extracted serial [parts[3]]: {serial}")

if __name__ == "__main__":
    diagnose()

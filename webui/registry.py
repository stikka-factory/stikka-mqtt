import threading
from typing import Dict, Optional, Callable, Any
import json
from pathlib import Path
from labelprinter.printer_abstract import LabelPrinter

import logger
log = logger.log


class PrinterRegistry:
    """
    Manages printer instances to ensure only one instance exists per physical printer.
    Multiple users/connections can access the same printer instance through this registry.
    Supports any printer manufacturer that implements the LabelPrinter interface.
    """
    
    _instance: Optional['PrinterRegistry'] = None
    _lock = threading.Lock()
    _printers: Dict[str, LabelPrinter] = {}
    _printers_lock = threading.Lock()
    _printer_factories: Dict[str, Callable] = {}
    _started_queues: set = set()  # Track which printers have their queues started
    
    def __new__(cls):
        """Singleton pattern for the registry itself."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    # Initialize default printer factory (avoid circular imports)
                    cls._initialize_default_factory()
        return cls._instance
    
    @classmethod
    def _initialize_default_factory(cls):
        """Initialize the default printer factories."""
        try:
            from labelprinter.printer_ql import BrotherPrinter
            cls._printer_factories["brother"] = cls._create_brother_printer
        except ImportError:
            log.warning("Could not import BrotherPrinter for factory initialization")
        
        try:
            from labelprinter.printer_debug import PrinterDebug
            cls._printer_factories["debug"] = cls._create_debug_printer
        except ImportError:
            log.warning("Could not import PrinterDebug for factory initialization")
    
    @staticmethod
    def _create_brother_printer(config):
        """Factory function for creating BrotherPrinter instances from config."""
        from labelprinter.printer_ql import BrotherPrinter
        return BrotherPrinter(
            identifier=config["identifier"],
            serial_number=config["serial_number"],
            backend=None,  # Will be set by BrotherPrinter
            backend_name=config.get("backend", "pyusb")
        )
    
    @staticmethod
    def _create_debug_printer(config):
        """Factory function for creating PrinterDebug instances from config."""
        from labelprinter.printer_debug import PrinterDebug
        return PrinterDebug(
            identifier=config.get("identifier", "DEBUG"),
            serial_number=config["serial_number"]
        )
    
    def get_printer(self, serial_number: str) -> Optional[LabelPrinter]:
        """
        Get a printer instance by serial number.
        Returns None if printer not found in registry.
        """
        with self._printers_lock:
            return self._printers.get(serial_number)
    
    def register_printer(self, printer: LabelPrinter) -> LabelPrinter:
        """
        Register a printer instance. If a printer with this serial number
        already exists, refreshes the existing instance from its own hardware
        and returns it.
        Automatically starts the printer's queue processing.
        """
        with self._printers_lock:
            serial = printer.serial_number
            if serial in self._printers:
                existing = self._printers[serial]
                # Keep object identity stable for UI/state references, but refresh
                # runtime state from the existing printer itself to avoid mixing
                # status objects between different physical devices.
                try:
                    if hasattr(existing, "update_status"):
                        existing.update_status()
                except Exception as exc:
                    log.warning(
                        f"Failed to refresh status for existing printer {serial}: {exc}"
                    )
                log.warning(
                    f"Printer with serial [bold magenta]{serial}[/bold magenta] "
                    f"already registered. Refreshed existing instance state."
                )
                return existing
            
            self._printers[serial] = printer
            log.info(f"Registered printer: [bold magenta]{serial}[/bold magenta]")
        
        # Start the queue for this printer (outside lock to avoid blocking)
        self.start_printer_queue(printer.serial_number)
        return printer
    
    def register_printers(self, printers: Dict[str, LabelPrinter]) -> Dict[str, LabelPrinter]:
        """
        Register multiple printer instances at once.
        Returns all registered printers (existing + newly registered).
        """
        for serial_number, printer in printers.items():
            self.register_printer(printer)
        
        return dict(self._printers)
    
    def discover(self, find_method: Callable, *args, **kwargs) -> Dict[str, LabelPrinter]:
        """
        Discover printers using a manufacturer-specific find method and register them.
        
        Args:
            find_method: A callable that returns Dict[str, LabelPrinter] (e.g., BrotherPrinter.find)
            *args, **kwargs: Arguments to pass to the find method
        
        Returns:
            All registered printers (existing + newly discovered).
        """
        discovered = find_method(*args, **kwargs)
        return self.register_printers(discovered)
    
    def get_all_printers(self) -> Dict[str, LabelPrinter]:
        """Get all registered printers."""
        with self._printers_lock:
            return dict(self._printers)
    
    def remove_printer(self, serial_number: str) -> bool:
        """Remove a printer from the registry and stop its queue."""
        self.stop_printer_queue(serial_number)
        with self._printers_lock:
            if serial_number in self._printers:
                del self._printers[serial_number]
                log.info(f"Removed printer from registry: [bold magenta]{serial_number}[/bold magenta]")
                return True
            return False
    
    def clear_all(self):
        """Clear all registered printers and stop all queues (use with caution)."""
        self._started_queues.clear()
        with self._printers_lock:
            self._printers.clear()
            log.info("Cleared all printers from registry")
    
    def start_printer_queue(self, serial_number: str) -> bool:
        """
        Start queue processing for a printer.
        
        Args:
            serial_number: Serial number of the printer
        
        Returns:
            True if queue was started, False if already running or printer not found
        """
        if serial_number in self._started_queues:
            return False  # Already started
        
        printer = self.get_printer(serial_number)
        if printer is None:
            return False  # Printer not found
        
        self._started_queues.add(serial_number)
        
        import threading
        queue_thread = threading.Thread(
            target=printer._handle_queue,
            name=f"PrinterQueue-{serial_number}",
            daemon=True
        )
        queue_thread.start()
        log.debug(f"Started queue for printer {serial_number}")
        return True
    
    def stop_printer_queue(self, serial_number: str) -> bool:
        """
        Flag a printer queue for stopping.
        
        Args:
            serial_number: Serial number of the printer
        
        Returns:
            True if queue was running and flagged to stop
        """
        if serial_number not in self._started_queues:
            return False
        
        printer = self.get_printer(serial_number)
        if printer is None:
            self._started_queues.discard(serial_number)
            return False
        
        # Set stop flag on printer queue
        if hasattr(printer, '_stop_queue'):
            printer._stop_queue = True
        
        self._started_queues.discard(serial_number)
        log.debug(f"Stopped queue for printer {serial_number}")
        return True

    def register_factory(self, printer_type: str, factory: Callable):
        """Register a factory function for a printer type."""
        self._printer_factories[printer_type] = factory
        log.info(f"Registered printer factory for type: {printer_type}")

    def load_from_config(self, config_path: str) -> Dict[str, LabelPrinter]:
        """Load printer configurations from a JSON file and register them."""
        config_file = Path(config_path)
        if not config_file.exists():
            log.error(f"Config file not found: {config_path}")
            return dict(self._printers)

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.load(f)
        except json.JSONDecodeError as exc:
            log.error(f"Invalid JSON in config file: {exc}")
            return dict(self._printers)
        except OSError as exc:
            log.error(f"Failed to read config file: {exc}")
            return dict(self._printers)

        for printer_config in config.get("printers", []):
            printer_type = printer_config.get("type")
            if not printer_type:
                log.warning("Printer config missing 'type' field, skipping")
                continue

            factory = self._printer_factories.get(printer_type)
            if factory is None:
                log.warning(
                    f"No factory registered for printer type {printer_type}. "
                    f"Available: {list(self._printer_factories.keys())}"
                )
                continue

            try:
                printer = factory(printer_config)
                self.register_printer(printer)
            except Exception as exc:
                log.error(f"Failed to create {printer_type} printer from config: {exc}")

        return dict(self._printers)


# Global singleton instance
PRINTER_REGISTRY = PrinterRegistry()

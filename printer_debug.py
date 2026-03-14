from labelprinter import LabelPrinter

import logger
log = logger.log
import time

class PrinterDebug(LabelPrinter):
    def __init__(self, identifier, serial_number):
        self.identifier = identifier
        self.serial_number = serial_number
        self.model = "Debug Printer"
        self.status = "Ready"
        self.print_queue = []

    @staticmethod
    def find():
        # Simulate finding a printer
        return [PrinterDebug("DEBUG123", "SN0001")]

    def _print(self, item):
        log.info(f"Printing item: {item}")
        self.status = "Printing"
        # Simulate printing time
        import time
        time.sleep(2)
        self.status = "Ready"
        log.info("Print job completed.")

    def _handle_queue(self):
        if self.print_queue:
            item = self.print_queue.pop(0)
            self._print(item)

    def update_status(self):
        log.info(f"Current status: {self.status}")

    def add_to_queue(self, item):
        log.info(f"Adding item to print queue: {item}")
        self.print_queue.append(item)

    def __str__(self):
        return f"PrinterDebug(identifier={self.identifier}, model={self.model}, status={self.status})"
    
if __name__ == "__main__":
    printer = PrinterDebug.find()[0]
    log.info(printer)
    printer.add_to_queue("Test Label 1")
    printer.check_queue() 
    printer.add_to_queue("Test Label 2")
    printer.add_to_queue("Test Label 3")
    printer.add_to_queue("Test Label 4")
    time.sleep(10)  # Wait for all print jobs to complete
    printer.add_to_queue("Test Label 5")
    printer.add_to_queue("Test Label 6")
    printer.add_to_queue("Test Label 7")
    printer.add_to_queue("Test Label 8")
    time.sleep(5)
    printer.add_to_queue("Test Label 9")
    printer.add_to_queue("Test Label 10")
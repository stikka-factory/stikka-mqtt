from abc import ABC, abstractmethod
import threading

import logger
log = logger.log

class LabelPrinter(ABC):

    @abstractmethod
    def _print(self, item):
        pass

    @abstractmethod
    def _handle_queue(self):
        pass
    
    @abstractmethod
    def update_status(self):
        pass

    @abstractmethod
    def add_to_queue(self, item):
        pass

    @abstractmethod
    def __repr__(self):
        pass

    def check_queue(self, interval = 2):
        self._handle_queue()
        # Restart the timer
        threading.Timer(interval, self.check_queue, [interval]).start()
        

    
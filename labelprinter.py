from abc import ABC, abstractmethod

class LabelPrinter(ABC):

    @abstractmethod
    def _print(self, item):
        pass
    
    @abstractmethod
    def update_status(self):
        pass

    @abstractmethod
    def add_to_queue(self, item):
        pass

    @abstractmethod
    def handle_queue(self):
        pass

    @abstractmethod
    def __str__(self):
        pass

    
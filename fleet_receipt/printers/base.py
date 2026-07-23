from abc import ABC, abstractmethod


class PrinterBackend(ABC):
    @abstractmethod
    def print_receipt(self, receipt: str) -> None:
        pass


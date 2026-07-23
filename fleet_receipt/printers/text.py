import sys
from typing import TextIO

from .base import PrinterBackend


class TextPrinter(PrinterBackend):
    def __init__(self, stream: TextIO = sys.stdout):
        self.stream = stream

    def print_receipt(self, receipt: str) -> None:
        self.stream.write(receipt)


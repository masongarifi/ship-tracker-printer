from pathlib import Path

from .base import PrinterBackend


class FilePrinter(PrinterBackend):
    """Write the exact receipt payload to a UTF-8 text file."""

    def __init__(self, output_path: Path):
        self.output_path = output_path

    def print_receipt(self, receipt: str) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with self.output_path.open("w", encoding="utf-8", newline="\n") as output:
            output.write(receipt)

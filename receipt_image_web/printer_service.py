import threading
from pathlib import Path

from fleet_receipt.printers.epson_usb import EpsonUsbPrinter, PrinterError


class PrinterBusyError(RuntimeError):
    pass


class PrinterService:
    def __init__(self, printer_factory=None):
        self._printer = EpsonUsbPrinter(printer_factory=printer_factory)
        self._lock = threading.Lock()

    def available(self) -> tuple[bool, str | None]:
        try:
            self._printer.check_available()
            return True, None
        except PrinterError as exc:
            return False, str(exc)

    def print_image(self, path: str | Path, copies: int, feed_lines: int, cut: bool) -> list[str]:
        if not self._lock.acquire(blocking=False):
            raise PrinterBusyError("Printer busy. Wait for the current job to finish.")
        try:
            warnings = []
            for _ in range(copies):
                warning = self._printer.print_image(path, feed_lines=feed_lines, cut=cut)
                if warning:
                    warnings.append(warning)
            return warnings
        finally:
            self._lock.release()

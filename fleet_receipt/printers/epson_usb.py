from collections.abc import Callable
from contextlib import suppress
from typing import Any

from .base import PrinterBackend

EPSON_VENDOR_ID = 0x04B8
TM_L90_PRODUCT_ID = 0x0202


class PrinterError(RuntimeError):
    """A physical-printer failure with an actionable user-facing message."""


class EpsonUsbPrinter(PrinterBackend):
    """ESC/POS backend for an Epson TM-L90 connected through a UB-U05 USB interface."""

    def __init__(
        self,
        vendor_id: int = EPSON_VENDOR_ID,
        product_id: int = TM_L90_PRODUCT_ID,
        printer_factory: Callable[..., Any] | None = None,
    ):
        self.vendor_id = vendor_id
        self.product_id = product_id
        self._printer_factory = printer_factory

    def print_receipt(self, receipt: str) -> None:
        self.print_and_finish(receipt)

    def print_and_finish(self, receipt: str) -> str | None:
        printer = self._connect()
        try:
            try:
                printer.text(receipt)
                printer.feed(6)
            except Exception as exc:
                raise _printer_error(exc, connected=True) from exc

            try:
                printer.cut(mode="FULL")
            except Exception as exc:
                return (
                    "receipt printed, but the full cut was not supported or failed; "
                    f"tear off the cleared receipt manually. Details: {exc}"
                )
            return None
        finally:
            close = getattr(printer, "close", None)
            if close:
                with suppress(Exception):
                    close()

    def _connect(self) -> Any:
        factory = self._printer_factory
        if factory is None:
            try:
                from escpos.printer import Usb
            except ImportError as exc:
                raise PrinterError(
                    "USB printer support is not installed. Install it with "
                    "`python -m pip install -e .` (or install `python-escpos[usb]`)."
                ) from exc
            factory = Usb

        try:
            return factory(self.vendor_id, self.product_id)
        except Exception as exc:
            raise _printer_error(exc, connected=False) from exc


def print_receipt(
    receipt: str,
    printer_factory: Callable[..., Any] | None = None,
) -> str | None:
    """Print a preformatted receipt; reusable by the CLI and future button service."""
    return EpsonUsbPrinter(printer_factory=printer_factory).print_and_finish(receipt)


def _printer_error(exc: Exception, connected: bool) -> PrinterError:
    detail = str(exc)
    normalized = detail.casefold()
    if isinstance(exc, PermissionError) or any(
        marker in normalized
        for marker in ("access denied", "permission", "not permitted", "errno 13")
    ):
        return PrinterError(
            "USB permission denied for Epson TM-L90 04b8:0202. "
            "On Linux, install a udev rule granting this user access, reload udev, "
            "and reconnect the printer; otherwise run with an account allowed to use USB."
        )
    if not connected or any(
        marker in normalized
        for marker in ("no such device", "device not found", "not found", "errno 19")
    ):
        return PrinterError(
            "Epson TM-L90 USB printer 04b8:0202 was not found. "
            "Connect and power on the printer, verify the UB-U05 USB cable, "
            "and confirm the device is visible to the operating system."
        )
    return PrinterError(
        "print job failed after connecting to the Epson TM-L90. "
        "Check the paper, cover, USB cable, and printer status, then retry. "
        f"Details: {exc}"
    )

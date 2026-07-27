from collections.abc import Callable
from contextlib import suppress
import logging
from typing import Any

from .base import PrinterBackend
from ..printer_formatting import PrinterReceipt

EPSON_VENDOR_ID = 0x04B8
TM_L90_PRODUCT_ID = 0x0202
TM_L90_OUT_ENDPOINT = 0x01
TM_L90_FEED_12_LINES = b"\x1b\x64\x0c"
TM_L90_PARTIAL_CUT = b"\x1d\x56\x01"
TM_L90_FINAL_SEQUENCE = TM_L90_FEED_12_LINES + TM_L90_PARTIAL_CUT
LOGGER = logging.getLogger(__name__)


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

    def print_and_finish(self, receipt: str | PrinterReceipt) -> str | None:
        printer = self._connect()
        try:
            try:
                if isinstance(receipt, PrinterReceipt):
                    for segment in receipt.segments:
                        printer.set(font=segment.font)
                        printer.text(segment.text)
                else:
                    printer.text(receipt)
            except Exception as exc:
                raise _printer_error(exc, connected=True) from exc

            try:
                self._write_final_sequence(printer)
            except Exception as exc:
                return (
                    "receipt printed, but the TM-L90 feed/cut sequence failed; "
                    f"tear off the cleared receipt manually. Details: {exc}"
                )
            return None
        finally:
            close = getattr(printer, "close", None)
            if close:
                with suppress(Exception):
                    close()

    def print_test(self) -> str | None:
        """Print a hardware-only diagnostic without fleet or receipt formatting."""
        return self.print_and_finish("EPSON TM-L90 TEST\n")

    def _write_final_sequence(self, printer: Any) -> None:
        device = printer.device
        endpoint = int(printer.out_ep)
        if endpoint & 0x80:
            raise PrinterError(
                f"configured USB endpoint 0x{endpoint:02x} is an IN endpoint; "
                f"the Epson TM-L90 requires OUT endpoint 0x{TM_L90_OUT_ENDPOINT:02x}."
            )
        if endpoint != TM_L90_OUT_ENDPOINT:
            raise PrinterError(
                f"unexpected Epson TM-L90 USB OUT endpoint 0x{endpoint:02x}; "
                f"expected 0x{TM_L90_OUT_ENDPOINT:02x}."
            )

        LOGGER.warning(
            "TM-L90 final raw bytes on USB OUT endpoint 0x%02x: %s",
            endpoint,
            TM_L90_FINAL_SEQUENCE.hex(" "),
        )
        _usb_write(device, endpoint, TM_L90_FEED_12_LINES, printer.timeout)
        _usb_write(device, endpoint, TM_L90_PARTIAL_CUT, printer.timeout)
        _flush_usb_output(device)

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
            return factory(
                self.vendor_id,
                self.product_id,
                out_ep=TM_L90_OUT_ENDPOINT,
            )
        except Exception as exc:
            raise _printer_error(exc, connected=False) from exc


def print_receipt(
    receipt: str | PrinterReceipt,
    printer_factory: Callable[..., Any] | None = None,
) -> str | None:
    """Print a preformatted receipt; reusable by the CLI and future button service."""
    return EpsonUsbPrinter(printer_factory=printer_factory).print_and_finish(receipt)


def print_test(printer_factory: Callable[..., Any] | None = None) -> str | None:
    """Run the standalone Epson USB feed-and-cut diagnostic."""
    return EpsonUsbPrinter(printer_factory=printer_factory).print_test()


def _usb_write(device: Any, endpoint: int, payload: bytes, timeout: Any) -> None:
    written = device.write(endpoint, payload, timeout)
    if written is not None and written != len(payload):
        raise OSError(f"short USB write: sent {written} of {len(payload)} bytes")


def _flush_usb_output(device: Any) -> None:
    """Flush buffered test transports; PyUSB bulk writes are synchronous."""
    flush = getattr(device, "flush", None)
    if flush is not None:
        flush()


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

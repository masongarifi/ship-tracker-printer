from argparse import Namespace

import pytest

from fleet_receipt import cli
from fleet_receipt.printers.epson_usb import EpsonUsbPrinter, PrinterError
from fleet_receipt.printer_formatting import PrinterReceipt, ReceiptSegment


class RecordingPrinter:
    def __init__(self):
        self.calls = []
        self.device = RecordingUsbDevice(self.calls)
        self.out_ep = 0x01
        self.timeout = 0

    def text(self, receipt):
        self.calls.append(("text", receipt))

    def set(self, **kwargs):
        self.calls.append(("set", kwargs))

    def close(self):
        self.calls.append(("close",))


class RecordingUsbDevice:
    def __init__(self, calls):
        self.calls = calls

    def write(self, endpoint, payload, timeout):
        self.calls.append(("write", endpoint, payload, timeout))
        return len(payload)

    def flush(self):
        self.calls.append(("flush",))


def factory_for(device):
    def factory(vendor, product, **kwargs):
        device.calls.append(("connect", vendor, product, kwargs))
        return device

    return factory


def test_usb_backend_receives_generated_receipt_and_finishes(caplog):
    device = RecordingPrinter()
    backend = EpsonUsbPrinter(printer_factory=factory_for(device))

    assert backend.print_and_finish("EXACT RECEIPT\n") is None
    assert device.calls == [
        ("connect", 0x04B8, 0x0202, {"out_ep": 0x01}),
        ("text", "EXACT RECEIPT\n"),
        ("write", 0x01, b"\x1b\x64\x0c", 0),
        ("write", 0x01, b"\x1d\x56\x01", 0),
        ("flush",),
        ("close",),
    ]
    assert "1b 64 0c 1d 56 01" in caplog.text
    assert "USB OUT endpoint 0x01" in caplog.text


def test_cut_failure_preserves_printed_receipt_and_returns_warning():
    device = RecordingPrinter()
    original_write = device.device.write

    def failed_cut(endpoint, payload, timeout):
        if payload == b"\x1d\x56\x01":
            device.calls.append(("write", endpoint, payload, timeout))
            raise OSError("cutter unavailable")
        return original_write(endpoint, payload, timeout)

    device.device.write = failed_cut
    warning = EpsonUsbPrinter(
        printer_factory=factory_for(device)
    ).print_and_finish("EXACT RECEIPT\n")

    assert "receipt printed" in warning
    assert device.calls == [
        ("connect", 0x04B8, 0x0202, {"out_ep": 0x01}),
        ("text", "EXACT RECEIPT\n"),
        ("write", 0x01, b"\x1b\x64\x0c", 0),
        ("write", 0x01, b"\x1d\x56\x01", 0),
        ("close",),
    ]


def test_print_command_selects_cached_data_and_uses_printer_generator(monkeypatch):
    cached_calls = []
    printed = []

    def fake_cached(cache, generated_at, width, fleet_profile):
        cached_calls.append((width, fleet_profile))
        return PrinterReceipt((ReceiptSegment("a", "CACHED RECEIPT\n"),))

    monkeypatch.setattr(cli, "render_cached_printer_report", fake_cached)
    monkeypatch.setattr(cli, "PositionCache", lambda: object())
    monkeypatch.setattr(cli, "print_usb_receipt", lambda receipt: printed.append(receipt))

    result = cli.main(["print", "--cached", "--fleet", "main", "--width", "42"])

    assert result == 0
    assert cached_calls == [(42, "main")]
    assert printed == [
        PrinterReceipt((ReceiptSegment("a", "CACHED RECEIPT\n"),))
    ]


def test_preview_and_print_use_same_receipt_generator(monkeypatch):
    generated = []
    previewed = []
    printed = []

    def fake_generate(args: Namespace):
        generated.append(args.command)
        return PrinterReceipt((ReceiptSegment("a", "SAME RECEIPT\n"),))

    monkeypatch.setattr(cli, "_generate_receipt", fake_generate)
    monkeypatch.setattr(
        cli,
        "TextPrinter",
        lambda: type("Printer", (), {"print_receipt": previewed.append})(),
    )
    monkeypatch.setattr(cli, "print_usb_receipt", lambda receipt: printed.append(receipt))

    assert cli.main(["preview", "--cached"]) == 0
    assert cli.main(["print", "--cached"]) == 0
    assert generated == ["preview", "print"]
    assert previewed == ["SAME RECEIPT\n"]
    assert printed == [
        PrinterReceipt((ReceiptSegment("a", "SAME RECEIPT\n"),))
    ]


def test_two_column_document_switches_to_small_font_for_ship_listings():
    device = RecordingPrinter()
    receipt = PrinterReceipt(
        (
            ReceiptSegment("a", "HEADER\n"),
            ReceiptSegment("b", "LEFT  RIGHT\n"),
            ReceiptSegment("a", "FOOTER\n"),
        )
    )

    assert EpsonUsbPrinter(
        printer_factory=factory_for(device)
    ).print_and_finish(receipt) is None

    assert ("set", {"font": "a"}) in device.calls
    assert ("set", {"font": "b"}) in device.calls
    assert ("text", "LEFT  RIGHT\n") in device.calls


def test_unavailable_usb_printer_is_actionable():
    def unavailable(vendor, product, **kwargs):
        raise OSError("No such device")

    with pytest.raises(PrinterError, match="was not found"):
        EpsonUsbPrinter(printer_factory=unavailable).print_receipt("receipt")


def test_usb_permission_error_during_job_is_actionable():
    device = RecordingPrinter()

    def denied(receipt):
        raise PermissionError("Access denied")

    device.text = denied

    with pytest.raises(PrinterError, match="USB permission denied"):
        EpsonUsbPrinter(printer_factory=factory_for(device)).print_receipt("receipt")

    assert device.calls == [
        ("connect", 0x04B8, 0x0202, {"out_ep": 0x01}),
        ("close",),
    ]


def test_print_command_handles_unavailable_printer(monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "_generate_receipt",
        lambda args: PrinterReceipt((ReceiptSegment("a", "receipt"),)),
    )

    def unavailable(receipt):
        raise PrinterError("Epson TM-L90 USB printer 04b8:0202 was not found.")

    monkeypatch.setattr(cli, "print_usb_receipt", unavailable)

    assert cli.main(["print", "--cached"]) == 2
    assert "was not found" in capsys.readouterr().err


def test_printer_test_skips_fleet_data_and_runs_usb_diagnostic(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "print_usb_test", lambda: calls.append("printer-test"))
    monkeypatch.setattr(
        cli,
        "_generate_receipt",
        lambda args: pytest.fail("printer-test must not generate a fleet receipt"),
    )

    assert cli.main(["printer-test"]) == 0
    assert calls == ["printer-test"]


def test_backend_printer_test_uses_text_feed_cut_flush_close_order():
    device = RecordingPrinter()

    assert EpsonUsbPrinter(printer_factory=factory_for(device)).print_test() is None
    assert device.calls == [
        ("connect", 0x04B8, 0x0202, {"out_ep": 0x01}),
        ("text", "EPSON TM-L90 TEST\n"),
        ("write", 0x01, b"\x1b\x64\x0c", 0),
        ("write", 0x01, b"\x1d\x56\x01", 0),
        ("flush",),
        ("close",),
    ]

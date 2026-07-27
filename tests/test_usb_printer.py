from argparse import Namespace

import pytest

from fleet_receipt import cli
from fleet_receipt.printers.epson_usb import EpsonUsbPrinter, PrinterError


class RecordingPrinter:
    def __init__(self):
        self.calls = []

    def text(self, receipt):
        self.calls.append(("text", receipt))

    def feed(self, lines):
        self.calls.append(("feed", lines))

    def _raw(self, payload):
        self.calls.append(("raw", payload))

    def close(self):
        self.calls.append(("close",))


def test_usb_backend_receives_generated_receipt_and_finishes():
    device = RecordingPrinter()
    backend = EpsonUsbPrinter(printer_factory=lambda vendor, product: device)

    assert backend.print_and_finish("EXACT RECEIPT\n") is None
    assert device.calls == [
        ("text", "EXACT RECEIPT\n"),
        ("feed", 12),
        ("raw", b"\x1d\x56\x42\x00"),
        ("close",),
    ]


def test_cut_failure_preserves_printed_receipt_and_returns_warning():
    device = RecordingPrinter()

    def failed_cut(payload):
        device.calls.append(("raw", payload))
        raise OSError("cutter unavailable")

    device._raw = failed_cut
    warning = EpsonUsbPrinter(
        printer_factory=lambda vendor, product: device
    ).print_and_finish("EXACT RECEIPT\n")

    assert "receipt printed" in warning
    assert device.calls == [
        ("text", "EXACT RECEIPT\n"),
        ("feed", 12),
        ("raw", b"\x1d\x56\x42\x00"),
        ("close",),
    ]


def test_print_command_selects_cached_data_and_uses_shared_generator(monkeypatch):
    cached_calls = []
    printed = []

    def fake_cached(cache, generated_at, width, fleet_profile):
        cached_calls.append((width, fleet_profile))
        return "CACHED RECEIPT\n"

    monkeypatch.setattr(cli, "render_cached_report", fake_cached)
    monkeypatch.setattr(cli, "PositionCache", lambda: object())
    monkeypatch.setattr(cli, "print_usb_receipt", lambda receipt: printed.append(receipt))

    result = cli.main(["print", "--cached", "--fleet", "main", "--width", "42"])

    assert result == 0
    assert cached_calls == [(42, "main")]
    assert printed == ["CACHED RECEIPT\n"]


def test_preview_and_print_use_same_receipt_generator(monkeypatch):
    generated = []
    previewed = []
    printed = []

    def fake_generate(args: Namespace):
        generated.append(args.command)
        return "SAME RECEIPT\n"

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
    assert printed == ["SAME RECEIPT\n"]


def test_unavailable_usb_printer_is_actionable():
    def unavailable(vendor, product):
        raise OSError("No such device")

    with pytest.raises(PrinterError, match="was not found"):
        EpsonUsbPrinter(printer_factory=unavailable).print_receipt("receipt")


def test_usb_permission_error_during_job_is_actionable():
    device = RecordingPrinter()

    def denied(receipt):
        raise PermissionError("Access denied")

    device.text = denied

    with pytest.raises(PrinterError, match="USB permission denied"):
        EpsonUsbPrinter(printer_factory=lambda vendor, product: device).print_receipt("receipt")

    assert device.calls == [("close",)]


def test_print_command_handles_unavailable_printer(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_generate_receipt", lambda args: "receipt")

    def unavailable(receipt):
        raise PrinterError("Epson TM-L90 USB printer 04b8:0202 was not found.")

    monkeypatch.setattr(cli, "print_usb_receipt", unavailable)

    assert cli.main(["print", "--cached"]) == 2
    assert "was not found" in capsys.readouterr().err

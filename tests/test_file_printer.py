from datetime import datetime
from io import StringIO

from fleet_receipt import cli
from fleet_receipt.cli import main
from fleet_receipt.config import load_fleet
from fleet_receipt.formatting import format_receipt
from fleet_receipt.printers.file import FilePrinter
from fleet_receipt.printers.text import TextPrinter
from fleet_receipt.providers.fixtures import FixturePositionProvider


def test_file_printer_writes_exact_receipt(tmp_path):
    output = tmp_path / "nested" / "receipt.txt"

    FilePrinter(output).print_receipt("SHIP\nPosition available\n")

    assert output.read_bytes() == b"SHIP\nPosition available\n"


def test_preview_can_write_snapshot_to_file(tmp_path):
    output = tmp_path / "fleet-receipt.txt"

    result = main(
        [
            "preview",
            "--fixtures",
            "--at",
            "2026-07-22T23:18:00Z",
            "--output",
            str(output),
        ]
    )

    fleet = load_fleet()
    positions = FixturePositionProvider().fetch_positions(fleet.vessels)
    expected = format_receipt(
        fleet,
        positions,
        datetime.fromisoformat("2026-07-22T23:18:00+00:00"),
        feed_health={"source": "Fixture", "status": "connected"},
    )
    assert result == 0
    assert output.read_text(encoding="utf-8") == expected


def test_terminal_preview_keeps_shared_inter_ship_blank_lines(monkeypatch):
    output = StringIO()
    monkeypatch.setattr(cli, "TextPrinter", lambda: TextPrinter(output))

    result = cli.main(
        [
            "preview",
            "--fixtures",
            "--at",
            "2026-07-22T23:18:00Z",
        ]
    )

    assert result == 0
    assert "Updated 8 minutes ago\n\nKONINGSDAM\n" in output.getvalue()

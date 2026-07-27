from dataclasses import replace

from fleet_receipt.formatting import format_receipt
from fleet_receipt.models import FleetData
from fleet_receipt.printer_formatting import (
    COLUMN_GAP,
    FONT_B,
    format_printer_receipt,
)


def test_two_column_ship_blocks_are_side_by_side(fleet, positions, report_time):
    receipt = format_printer_receipt(
        fleet, positions, report_time, width=42, two_column=True
    )

    assert "EURODAM" in receipt.text
    eurodam_line = next(
        line for line in receipt.text.splitlines() if line.startswith("EURODAM")
    )
    assert "KONINGSDAM" in eurodam_line
    assert "  " in eurodam_line
    assert any(segment.font == FONT_B for segment in receipt.segments)
    assert any(
        segment.font == FONT_B
        and segment.emphasized
        and "EURODAM" in segment.text
        for segment in receipt.segments
    )
    name_segment_index = next(
        index
        for index, segment in enumerate(receipt.segments)
        if segment.emphasized and "EURODAM" in segment.text
    )
    assert receipt.segments[name_segment_index + 1].emphasized is False


def test_column_wrapping_never_spills_into_other_column(
    fleet, positions, report_time
):
    changed = dict(positions)
    changed["koningsdam"] = replace(
        changed["koningsdam"],
        destination=(
            "A deliberately long destination with several readable words "
            "that must remain inside the right column"
        ),
    )
    receipt = format_printer_receipt(
        fleet, changed, report_time, width=42, two_column=True
    )
    listing_lines = [
        line
        for segment in receipt.segments
        if segment.font == FONT_B
        for line in segment.text.splitlines()
        if line
    ]

    assert listing_lines
    assert all(len(line) <= 56 for line in listing_lines)
    assert all(
        line.ljust(56)[26:30] == " " * COLUMN_GAP for line in listing_lines
    )


def test_odd_ship_count_leaves_final_right_column_empty(
    fleet, positions, report_time
):
    selected = fleet.vessels[:3]
    small_fleet = FleetData(
        ("Holland America Line",),
        selected,
    )
    selected_positions = {
        vessel.name.casefold(): positions[vessel.name.casefold()]
        for vessel in selected
    }
    receipt = format_printer_receipt(
        small_fleet,
        selected_positions,
        report_time,
        width=42,
        two_column=True,
    )
    final_name = selected[-1].name.upper()
    final_line = next(
        line for line in receipt.text.splitlines() if line.startswith(final_name)
    )

    assert final_line[:26].strip() == final_name
    assert final_line[30:].strip() == ""


def test_two_column_printer_output_is_ascii_only(fleet, positions, report_time):
    receipt = format_printer_receipt(
        fleet, positions, report_time, width=42, two_column=True
    )

    assert receipt.text.isascii()
    assert "DEST " in receipt.text
    assert "@" in receipt.text
    assert "→" not in receipt.text
    assert "°" not in receipt.text


def test_movement_destination_and_age_are_compact(
    fleet, positions, report_time
):
    receipt = format_printer_receipt(
        fleet, positions, report_time, width=42, two_column=True
    )

    assert "UNDERWAY|320 deg|14.2 kt" in receipt.text
    assert "DEST Ketchikan" in receipt.text
    assert "AIS 8 min ago" in receipt.text
    assert "! AIS 11 hr ago" in receipt.text
    assert "CRS " not in receipt.text
    assert "Updated " not in receipt.text


def test_coordinates_stay_on_one_ascii_line(fleet, positions, report_time):
    receipt = format_printer_receipt(
        fleet, positions, report_time, width=42, two_column=True
    )

    coordinate_line = next(
        line
        for line in receipt.text.splitlines()
        if "58 18.1N | 134 25.2W" in line
    )
    assert "52 00.0N | 128 00.0W" in coordinate_line
    assert coordinate_line.isascii()


def test_full_width_sections_remain_font_a(fleet, positions, report_time):
    receipt = format_printer_receipt(
        fleet, positions, report_time, width=42, two_column=True
    )
    full_width_text = "".join(
        segment.text for segment in receipt.segments if segment.font == "a"
    )

    assert "FLEET OPERATIONS BRIEF" in full_width_text
    assert "HAL Reporting: 11 / 11" in full_width_text
    assert "AIS Source: Terrestrial" in full_width_text
    assert "HOLLAND AMERICA LINE" in full_width_text
    assert "SEABOURN" in full_width_text
    assert "Latest available AIS positions" in full_width_text
    assert "=" * 42 in full_width_text
    assert "-" * 42 in full_width_text


def test_disabled_setting_returns_existing_single_column_receipt(
    fleet, positions, report_time
):
    expected = format_receipt(fleet, positions, report_time, width=42)
    receipt = format_printer_receipt(
        fleet, positions, report_time, width=42, two_column=False
    )

    assert receipt.text == expected
    assert len(receipt.segments) == 1
    assert receipt.segments[0].font == "a"


def test_web_formatter_remains_single_column_and_unchanged(
    fleet, positions, report_time
):
    web_receipt = format_receipt(fleet, positions, report_time, width=42)
    printer_receipt = format_printer_receipt(
        fleet, positions, report_time, width=42, two_column=True
    ).text

    assert "EURODAM\n" in web_receipt
    assert "EURODAM" in printer_receipt
    assert web_receipt != printer_receipt
    assert "EURODAM" not in web_receipt.splitlines()[0]

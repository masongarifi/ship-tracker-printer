import re
from dataclasses import replace

from fleet_receipt.formatting import format_receipt
from fleet_receipt.briefing import VesselBrief
from fleet_receipt.models import FleetData
from fleet_receipt.printer_formatting import (
    COLUMN_GAP,
    FONT_B_PRINTABLE_WIDTH,
    FONT_B,
    PrinterReceipt,
    _format_pairs,
    _movement_rows,
    _receipt_location,
    _ship_slots,
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
    assert all(len(line) <= FONT_B_PRINTABLE_WIDTH for line in listing_lines)
    assert all(
        line.ljust(FONT_B_PRINTABLE_WIDTH)[25:29] == " " * COLUMN_GAP
        for line in listing_lines
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

    assert final_line[:25].strip() == final_name
    assert final_line[29:].strip() == ""


def test_two_column_printer_output_is_ascii_only(fleet, positions, report_time):
    receipt = format_printer_receipt(
        fleet, positions, report_time, width=42, two_column=True
    )

    assert receipt.text.isascii()
    assert "DEST " in receipt.text
    assert "@" not in receipt.text
    assert "→" not in receipt.text
    assert "°" not in receipt.text


def test_underway_reserves_status_speed_and_course_rows(
    fleet, positions, report_time
):
    receipt = format_printer_receipt(
        fleet, positions, report_time, width=42, two_column=True
    )

    assert "UNDERWAY" in receipt.text
    assert "14.2 kn" in receipt.text
    assert "320 deg NW" in receipt.text
    assert "DEST Ketchikan" in receipt.text
    assert "AIS 8 min ago" in receipt.text
    assert "AIS 11 hr ago" in receipt.text
    assert "! AIS" not in receipt.text
    assert "CRS " not in receipt.text
    assert "Updated " not in receipt.text


def test_underway_with_missing_speed_keeps_blank_speed_row(positions):
    position = replace(
        positions["koningsdam"],
        speed_knots=None,
        course_degrees=123.0,
        navigational_status="Under way",
    )

    assert _movement_rows(position, 26) == (
        "UNDERWAY",
        " ",
        "123 deg SE",
    )


def test_moored_keeps_reserved_speed_and_course_rows(positions):
    position = replace(
        positions["koningsdam"],
        navigational_status="Moored",
        speed_knots=0.0,
        course_degrees=90.0,
    )

    assert _movement_rows(position, 26) == ("MOORED", " ", " ")


def test_anchored_keeps_reserved_speed_and_course_rows(positions):
    position = replace(
        positions["koningsdam"],
        navigational_status="At anchor",
        speed_knots=None,
        course_degrees=None,
    )

    assert _movement_rows(position, 26) == ("AT ANCHOR", " ", " ")


def test_unknown_and_long_status_fit_one_reserved_line(positions):
    unknown = replace(
        positions["koningsdam"],
        navigational_status=None,
        speed_knots=None,
        course_degrees=None,
    )
    long_status = replace(
        positions["koningsdam"],
        navigational_status=(
            "Power driven vessel pushing ahead or towing alongside"
        ),
    )

    assert _movement_rows(unknown, 26) == ("UNKNOWN", " ", " ")
    status, speed, course = _movement_rows(long_status, 26)
    assert len(status) <= 26
    assert speed == " "
    assert course == " "


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


def test_missing_ship_prints_only_no_ais_message(
    fleet, positions, report_time
):
    changed = dict(positions)
    changed.pop("volendam")
    receipt = format_printer_receipt(
        fleet,
        changed,
        report_time,
        width=42,
        two_column=True,
    )
    missing_section = receipt.text.split("NO RECENT AIS (1)", 1)[1]

    assert "VOLENDAM" in missing_section
    assert missing_section.count("[No AIS]") == 1
    assert "No cached position" not in missing_section
    assert "[NO AIS]" not in missing_section
    assert "\n!" not in missing_section
    assert "Likely outside terrestrial AIS coverage." not in missing_section


def test_long_ship_name_wraps_without_crossing_columns(
    fleet, positions, report_time
):
    long_name = "A VERY LONG TEST VESSEL NAME FOR RECEIPT"
    changed_vessel = replace(fleet.vessels[0], name=long_name)
    changed_fleet = FleetData(
        fleet.cruise_line_order,
        (changed_vessel, *fleet.vessels[1:]),
    )
    changed_positions = dict(positions)
    changed_positions.pop("eurodam")
    changed_positions[long_name.casefold()] = replace(
        positions["eurodam"],
        vessel_name=long_name,
    )
    receipt = format_printer_receipt(
        changed_fleet,
        changed_positions,
        report_time,
        width=42,
        two_column=True,
    )
    emphasized_lines = [
        line
        for segment in receipt.segments
        if segment.emphasized
        for line in segment.text.splitlines()
    ]

    assert any("A VERY LONG TEST VESSEL" in line for line in emphasized_lines)
    assert all(
        len(line) <= FONT_B_PRINTABLE_WIDTH for line in emphasized_lines
    )
    assert all(
        line.ljust(FONT_B_PRINTABLE_WIDTH)[25:29] == " " * COLUMN_GAP
        for line in emphasized_lines
    )


def test_left_and_right_status_rows_stay_aligned(
    fleet, positions, report_time
):
    changed = dict(positions)
    changed["eurodam"] = replace(
        changed["eurodam"],
        navigational_status="Moored",
        speed_knots=None,
        course_degrees=None,
    )
    changed["koningsdam"] = replace(
        changed["koningsdam"],
        navigational_status="Under way",
        speed_knots=12.4,
        course_degrees=123.0,
    )
    receipt = format_printer_receipt(
        fleet, changed, report_time, width=42, two_column=True
    )
    lines = receipt.text.splitlines()
    status_index = next(
        index
        for index, line in enumerate(lines)
        if line.startswith("MOORED") and "UNDERWAY" in line
    )

    assert lines[status_index][:25].strip() == "MOORED"
    assert lines[status_index][29:].strip() == "UNDERWAY"
    assert lines[status_index + 1][:25].strip() == ""
    assert lines[status_index + 1][29:].strip() == "12.4 kn"
    assert lines[status_index + 2][:25].strip() == ""
    assert lines[status_index + 2][29:].strip() == "123 deg SE"


def test_eurodam_koningsdam_location_fields_wrap_before_pairing(positions):
    eurodam = VesselBrief(
        name="EURODAM",
        location="Inside Passage",
        landmark="24.6 nm S of Juneau",
        coordinates="49 29.1N 127 00.8W",
        movement="Moored",
        voyage=None,
        utc_time="09:00",
        local_time="01:00 (-1 Seattle)",
        age_heading="Updated",
        age="4 hours ago",
    )
    koningsdam = VesselBrief(
        name="KONINGSDAM",
        location="Inside Passage",
        landmark="80.6 nm N of Ketchikan",
        coordinates="54 29.1N 131 38.9W",
        movement="Underway",
        voyage=None,
        utc_time="09:05",
        local_time="01:05 (-1 Seattle)",
        age_heading="Updated",
        age="3 hours ago",
    )
    blocks = [
        _ship_slots(eurodam, positions["eurodam"], 25),
        _ship_slots(koningsdam, positions["koningsdam"], 25),
    ]
    receipt = PrinterReceipt(tuple(_format_pairs(blocks, 25)))
    lines = receipt.text.splitlines()
    location_index = next(
        index
        for index, line in enumerate(lines)
        if line.startswith("Inside Passage")
    )

    assert lines[location_index][:25].strip() == "Inside Passage"
    assert lines[location_index][29:].strip() == "Inside Passage"
    assert lines[location_index + 1][:25].strip() == "25nm S of Juneau"
    assert lines[location_index + 1][29:].strip() == "81nm N of Ketchikan"
    assert not any(line.strip() in {"m", "n"} for line in lines)
    assert not any(re.search(r"\d+\s+nm\b", line) for line in lines)
    assert not any(line.lstrip().startswith("@") for line in lines)
    assert all(len(line) <= FONT_B_PRINTABLE_WIDTH for line in lines)


def test_receipt_locations_use_seattle_and_usps_abbreviations():
    assert _receipt_location("Same as Seattle") == "Seattle"
    assert _receipt_location("Juneau, Alaska") == "Juneau, AK"
    assert _receipt_location("Seattle, Washington") == "Seattle, WA"
    assert _receipt_location("Los Angeles, California") == "Los Angeles, CA"
    assert _receipt_location("Miami, Florida") == "Miami, FL"
    assert _receipt_location("Honolulu, Hawaii") == "Honolulu, HI"
    assert _receipt_location("Galveston, Texas") == "Galveston, TX"
    assert _receipt_location("115nm W of Seattle, Washington") == (
        "115nm W of Seattle, WA"
    )


def test_receipt_local_time_uses_seattle_instead_of_same_as_seattle(
    fleet, positions, report_time
):
    receipt = format_printer_receipt(
        fleet,
        positions,
        report_time,
        width=42,
        two_column=True,
    )

    assert "Same as Seattle" not in receipt.text
    assert "LOCAL 16:15 (Seattle)" in receipt.text


def test_receipt_locations_leave_cities_countries_and_non_us_regions_unchanged():
    assert _receipt_location("Washington") == "Washington"
    assert _receipt_location("Vancouver, British Columbia") == (
        "Vancouver, British Columbia"
    )
    assert _receipt_location("Cozumel, Mexico") == "Cozumel, Mexico"
    assert _receipt_location("Yokohama, Japan") == "Yokohama, Japan"


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

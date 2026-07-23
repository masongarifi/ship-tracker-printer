from dataclasses import replace

from fleet_receipt.formatting import format_receipt


def test_every_vessel_appears_exactly_once(fleet, positions, report_time):
    receipt = format_receipt(fleet, positions, report_time)
    for vessel in fleet.vessels:
        heading = f"{vessel.name.upper()}\n{'─' * len(vessel.name)}"
        assert receipt.count(heading) == 1


def test_underway_movement_is_one_compact_line(fleet, positions, report_time):
    receipt = format_receipt(fleet, positions, report_time)
    koningsdam = receipt.split("KONINGSDAM", 1)[1].split("NIEUW AMSTERDAM", 1)[0]
    assert "\nUNDERWAY CRS 320° at 14.2 kts\n" in koningsdam
    assert "Inside Passage" in koningsdam


def test_stale_warning(fleet, positions, report_time):
    receipt = format_receipt(fleet, positions, report_time)
    assert "Last AIS report 11 hours ago" in receipt


def test_missing_position_output(fleet, positions, report_time):
    positions = dict(positions)
    del positions["volendam"]
    receipt = format_receipt(fleet, positions, report_time)
    assert "NO RECENT AIS (1)" in receipt
    assert "\nVOLENDAM\n" in receipt
    assert "Likely outside terrestrial AIS coverage." in receipt
    assert "VOLENDAM\n────────" not in receipt


def test_fleet_summary_counts_reporting_vessels(fleet, positions, report_time):
    positions = dict(positions)
    del positions["eurodam"]
    del positions["seabourn quest"]
    receipt = format_receipt(fleet, positions, report_time)
    assert "HAL Reporting: 10 / 11" in receipt
    assert "Seabourn Reporting: 4 / 5" in receipt
    assert "AIS Source: Terrestrial" in receipt


def test_destination_and_eta_only_print_when_underway(fleet, positions, report_time):
    changed = dict(positions)
    changed["eurodam"] = replace(
        changed["eurodam"],
        destination="Rotterdam",
        reported_eta="2026-07-26T07:00:00+00:00",
    )
    receipt = format_receipt(fleet, changed, report_time)
    eurodam = receipt.split("EURODAM", 1)[1].split("KONINGSDAM", 1)[0]
    koningsdam = receipt.split("KONINGSDAM", 1)[1].split("NIEUW AMSTERDAM", 1)[0]

    assert "Destination" not in eurodam
    assert "ETA" not in eurodam
    assert "Destination Ketchikan" in koningsdam


def test_moored_and_anchored_blocks_hide_speed_and_course(
    fleet, positions, report_time
):
    changed = dict(positions)
    changed["eurodam"] = replace(
        changed["eurodam"], speed_knots=0.0, course_degrees=195.0
    )
    changed["rotterdam"] = replace(
        changed["rotterdam"], speed_knots=0.2, course_degrees=77.0
    )
    receipt = format_receipt(fleet, changed, report_time)
    eurodam = receipt.split("EURODAM", 1)[1].split("KONINGSDAM", 1)[0]
    rotterdam = receipt.split("\nROTTERDAM\n─────────", 1)[1].split(
        "\nVOLENDAM\n────────", 1
    )[0]

    assert "\nMOORED\n" in eurodam
    assert "kt" not in eurodam
    assert "Course" not in eurodam
    assert "\nAT ANCHOR\n" in rotterdam
    assert "kt" not in rotterdam
    assert "Course" not in rotterdam


def test_vessel_block_has_no_internal_blank_lines(fleet, positions, report_time):
    receipt = format_receipt(fleet, positions, report_time)
    block = receipt.split("KONINGSDAM", 1)[1].split("NIEUW AMSTERDAM", 1)[0]
    assert "\n\n" not in block.strip()


def test_route_and_eta_are_friendly_on_receipt(fleet, positions, report_time):
    changed = dict(positions)
    changed["koningsdam"] = replace(
        changed["koningsdam"],
        destination="TE COB > GB DVR",
        reported_eta="2026-07-24T02:30:00+00:00",
    )

    receipt = format_receipt(fleet, changed, report_time)
    block = receipt.split("KONINGSDAM", 1)[1].split("NIEUW AMSTERDAM", 1)[0]

    assert "Te Cob → Dover, United Kingdom" in block
    assert "ETA 24 Jul 0230 UTC" in block
    assert "GB DVR" not in block


def test_coordinates_appear_exactly_once_per_position(fleet, positions, report_time):
    from fleet_receipt.locations import format_coordinates

    receipt = format_receipt(fleet, positions, report_time)
    for position in positions.values():
        coordinates = format_coordinates(position.latitude, position.longitude)
        assert receipt.count(coordinates) == 1


def test_narrow_receipt_splits_coordinate_pair(fleet, positions, report_time):
    receipt = format_receipt(fleet, positions, report_time, width=15)
    eurodam = receipt.split("EURODAM", 1)[1].split("KONINGSDAM", 1)[0]
    assert "58°18.1'N\n134°25.2'W" in eurodam


def test_line_wrapping(fleet, positions, report_time):
    changed = dict(positions)
    changed["koningsdam"] = replace(
        changed["koningsdam"], destination="A destination with several readable words"
    )
    receipt = format_receipt(fleet, changed, report_time, width=30)
    assert all(len(line) <= 30 for line in receipt.splitlines())
    assert "destinatio\nn" not in receipt

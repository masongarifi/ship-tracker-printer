from datetime import datetime, timezone

import pytest

from fleet_receipt.formatting_helpers import (
    format_course,
    format_destination,
    format_eta,
    format_movement,
    format_position_age,
    format_voyage,
    should_show_course,
    should_show_speed,
)


def test_course_is_zero_padded_and_invalid_values_are_omitted():
    assert format_course(87.2) == "Course 087°"
    assert format_course(None) is None
    assert format_course(360) is None


def test_eta_uses_bridge_watch_format():
    assert format_eta("2026-07-26T07:00:00+00:00") == "ETA 26 Jul 0700 UTC"
    assert format_eta(None) is None


def test_stale_position_keeps_age_but_changes_classification():
    reported = datetime(2026, 7, 22, 1, tzinfo=timezone.utc)
    generated = datetime(2026, 7, 22, 19, tzinfo=timezone.utc)
    assert format_position_age(reported, generated, 6) == ("18 hours", True)


def test_moored_and_anchored_hide_speed_and_course():
    for status in ("Moored", "At anchor"):
        assert not should_show_speed(status, 0.0)
        assert not should_show_course(status, 0.0, 195.0)


def test_underway_shows_valid_speed_and_course():
    assert should_show_speed("Underway", 15.5)
    assert should_show_course("Underway", 15.5, 77.0)


def test_missing_or_invalid_navigation_values_are_hidden():
    assert not should_show_speed("Underway", None)
    assert not should_show_course("Underway", 12.0, None)
    assert not should_show_course("Underway", 12.0, 360.0)


def test_destination_codes_become_friendly_compact_voyage_lines():
    assert format_destination("GB DVR") == "Dover, United Kingdom"
    assert format_voyage("GB DVR", "ETA 26 Jul 0700 UTC") == (
        "Destination Dover, United Kingdom\nETA 26 Jul 0700 UTC"
    )


@pytest.mark.parametrize(
    "code, expected",
    [
        ("GB SOU", "Southampton, United Kingdom"),
        ("NLRTM", "Rotterdam, Netherlands"),
        ("BE ANR", "Antwerp, Belgium"),
        ("DE HAM", "Hamburg, Germany"),
        ("FR LEH", "Le Havre, France"),
        ("US SEA", "Seattle, Washington"),
        ("USLAX", "Los Angeles, California"),
        ("CA VAN", "Vancouver, British Columbia"),
        ("SG SIN", "Singapore"),
    ],
)
def test_common_unlocodes_expand_to_friendly_ports(code, expected):
    assert format_destination(code) == expected


def test_route_translates_known_endpoint_and_preserves_unknown_endpoint():
    assert format_destination("TE COB > GB DVR") == (
        "Te Cob → Dover, United Kingdom"
    )
    assert format_destination("GB SOU > NL RTM") == (
        "Southampton, United Kingdom → Rotterdam, Netherlands"
    )


def test_unknown_destination_falls_back_gracefully():
    assert format_destination("SOME TERMINAL") == "Some Terminal"


def test_compact_movement_line_omits_invalid_values():
    assert format_movement("Underway", 18.3, 75.0) == (
        "UNDERWAY CRS 075° at 18.3 kts"
    )
    assert format_movement("Moored", 0.0, 195.0) == "MOORED"
    assert format_movement("Underway", 12.0, None) == "UNDERWAY at 12.0 kts"

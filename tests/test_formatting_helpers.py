from datetime import datetime, timezone

from fleet_receipt.formatting_helpers import (
    format_course,
    format_eta,
    format_position_age,
    should_show_course,
    should_show_speed,
)


def test_course_is_zero_padded_and_invalid_values_are_omitted():
    assert format_course(87.2) == "Course 087°"
    assert format_course(None) is None
    assert format_course(360) is None


def test_eta_uses_bridge_watch_format():
    assert format_eta("2026-07-26T07:00:00+00:00") == "ETA 26 Jul 0700"
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

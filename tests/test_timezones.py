from datetime import datetime, timezone

from fleet_receipt.models import Location, Position
from fleet_receipt.timezones import estimate_local_time, nautical_offset_hours, relative_to_seattle


def position(instant, longitude=0):
    return Position("Test", 0, longitude, 1, 1, "Underway", None, None, instant, "test")


def test_relative_wording():
    assert relative_to_seattle(0) == "Same time as Seattle"
    assert relative_to_seattle(60) == "1 hour ahead of Seattle"
    assert relative_to_seattle(-60) == "1 hour behind Seattle"
    assert relative_to_seattle(480) == "8 hours ahead of Seattle"
    assert relative_to_seattle(-210) == "3 hours 30 minutes behind Seattle"
    assert relative_to_seattle(345) == "5 hours 45 minutes ahead of Seattle"


def test_seattle_daylight_saving_and_standard_time():
    utc = Location("UTC", "UTC", "region")
    summer = estimate_local_time(position(datetime(2026, 7, 22, 23, tzinfo=timezone.utc)), utc)
    winter = estimate_local_time(position(datetime(2026, 1, 22, 23, tzinfo=timezone.utc)), utc)
    assert summer.offset_minutes == 420
    assert winter.offset_minutes == 480


def test_real_half_hour_timezone_is_preserved():
    india = Location("India", "Asia/Kolkata", "region")
    estimate = estimate_local_time(position(datetime(2026, 7, 22, 23, tzinfo=timezone.utc)), india)
    assert estimate.offset_minutes == 750
    assert relative_to_seattle(estimate.offset_minutes) == "12 hours 30 minutes ahead of Seattle"


def test_longitude_fallback_east_and_west():
    assert nautical_offset_hours(30) == 2
    assert nautical_offset_hours(-30) == -2
    assert nautical_offset_hours(7.4) == 0
    assert nautical_offset_hours(7.6) == 1


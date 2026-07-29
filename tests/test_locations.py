from fleet_receipt.locations import (
    format_coordinates,
    get_friendly_location,
    get_nearest_landmark,
    resolve_location,
)
from fleet_receipt.models import Position
from datetime import datetime, timezone


def test_marine_coordinate_format():
    assert format_coordinates(58.405, -21.3116667) == "58°24.3'N 021°18.7'W"


def test_specific_marine_features_take_priority():
    assert get_friendly_location(50.2, 0.2) == "English Channel"
    assert get_friendly_location(38.2, 15.6) == "Strait of Messina"


def test_nearby_port_is_readable():
    assert get_friendly_location(1.2644, 103.82) == "Near Singapore, Singapore"


def test_broad_ocean_fallback_is_not_generic():
    assert get_friendly_location(58.0, -30.0) == "North Atlantic Ocean"


def test_amsterdam_port_outranks_north_sea_and_rotterdam():
    latitude, longitude = 52.3783, 4.9167
    assert get_friendly_location(latitude, longitude) == "Port of Amsterdam"
    assert get_nearest_landmark(latitude, longitude) == "Amsterdam, Netherlands"
    assert "Rotterdam" not in get_friendly_location(latitude, longitude)


def test_offshore_location_can_use_water_and_nearest_landmark():
    latitude, longitude = 50.2, 0.2
    assert get_friendly_location(latitude, longitude) == "English Channel"
    assert get_nearest_landmark(latitude, longitude) == "70 nm SW of Dover, England"


def test_fixture_has_readable_location_for_every_position(positions):
    for position in positions.values():
        assert resolve_location(position).name


def _nieuw_statendam(status):
    return Position(
        "Nieuw Statendam",
        58 + 52.3 / 60,
        5 + 44.8 / 60,
        0.0,
        None,
        status,
        None,
        None,
        datetime(2026, 7, 29, tzinfo=timezone.utc),
        "test",
    )


def test_moored_ship_prefers_stavanger_over_north_sea():
    location = resolve_location(_nieuw_statendam("Moored"))
    assert location.name == "Stavanger, Norway"
    assert location.kind == "port"
    assert location.timezone_name == "Europe/Oslo"


def test_anchored_ship_in_normal_port_anchorage_prefers_stavanger():
    assert resolve_location(_nieuw_statendam("At anchor")).name == "Stavanger, Norway"


def test_underway_ship_offshore_keeps_body_of_water_fallback():
    assert resolve_location(_nieuw_statendam("Under way using engine")).name == "North Sea"

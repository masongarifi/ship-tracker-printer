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


def test_amsterdam_city_outranks_port_and_north_sea():
    latitude, longitude = 52.3783, 4.9167
    assert get_friendly_location(latitude, longitude) == "Amsterdam, Netherlands"
    assert get_nearest_landmark(latitude, longitude) is None
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


def test_moored_oslo_uses_general_nearest_place_lookup(monkeypatch):
    monkeypatch.setattr(
        "fleet_receipt.locations.nearest_unlocode",
        lambda latitude, longitude, limit: (2.1, "Oslo, Norway", "city"),
    )
    position = Position(
        "Seabourn Ovation",
        59 + 54.4 / 60,
        10 + 43.0 / 60,
        0.0,
        None,
        "Moored",
        None,
        None,
        datetime(2026, 8, 4, tzinfo=timezone.utc),
        "test",
    )

    location = resolve_location(position)

    assert location.name == "Oslo, Norway"
    assert location.kind == "city"


def test_anchored_outside_city_gets_anchored_off_wording(monkeypatch):
    monkeypatch.setattr(
        "fleet_receipt.locations.nearest_unlocode",
        lambda latitude, longitude, limit: (18.52, "Juneau, Alaska", "city"),
    )
    position = Position(
        "Test Ship", 58.1, -134.5, 0.0, None, "At anchor", None, None,
        datetime(2026, 8, 4, tzinfo=timezone.utc), "test",
    )

    assert resolve_location(position).name == "Anchored off Juneau, Alaska"

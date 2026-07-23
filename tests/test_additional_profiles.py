from datetime import datetime, timezone
import html
import json
import re

import pytest
from fastapi.testclient import TestClient

from fleet_receipt.cache import PositionCache
from fleet_receipt.config import ConfigurationError, load_fleet
from fleet_receipt.dashboard import build_dashboard, search_vessels
from fleet_receipt.models import Position
from fleet_receipt.web import create_app


NOW = datetime(2026, 7, 23, 16, 0, tzinfo=timezone.utc)
PROFILES = {
    "msc": ("MSC Cruises", 23, "/msc", "/profile/msc", "MSC Euribia"),
    "ncl": (
        "Norwegian Cruise Line",
        21,
        "/ncl",
        "/profile/ncl",
        "NCL Aqua",
    ),
    "dcl": ("Disney Cruise Line", 8, "/dcl", "/profile/dcl", "Disney Wish"),
    "vv": (
        "Virgin Voyages",
        4,
        "/virgin-voyages",
        "/profile/vv",
        "Virgin Scarlet Lady",
    ),
    "oceania": (
        "Oceania Cruises",
        8,
        "/oceania",
        "/profile/oceania",
        "Oceania Vista",
    ),
    "regent": (
        "Regent Seven Seas Cruises",
        6,
        "/regent",
        "/profile/regent",
        "Regent Explorer",
    ),
}


def _client(tmp_path):
    return TestClient(
        create_app(
            cache=PositionCache(tmp_path / "positions.sqlite3"),
            now_factory=lambda: NOW,
        )
    )


@pytest.mark.parametrize("profile", PROFILES)
def test_each_additional_profile_loads(profile):
    line_name, count, _, _, _ = PROFILES[profile]
    fleet = load_fleet(profile=profile)

    assert fleet.cruise_line_order == (line_name,)
    assert len(fleet.vessels) == count
    assert all(vessel.active for vessel in fleet.vessels)


@pytest.mark.parametrize("profile", PROFILES)
def test_each_additional_fleet_route_returns_200(profile, tmp_path):
    line_name, _, route, profile_route, _ = PROFILES[profile]
    client = _client(tmp_path)

    for path in (route, profile_route):
        response = client.get(path)
        assert response.status_code == 200
        assert html.escape(line_name) in response.text
        assert 'id="fleet-map"' in response.text
        assert "leaflet@1.9.4/dist/leaflet.css" in response.text
        assert "/static/dashboard.js" in response.text


def test_homepage_cards_link_to_each_additional_fleet(tmp_path):
    response = _client(tmp_path).get("/")

    assert response.status_code == 200
    for line_name, count, route, _, _ in PROFILES.values():
        assert f'href="http://testserver{route}"' in response.text
        assert html.escape(line_name) in response.text
        assert f"{count} ships" in response.text
    assert "208" in response.text


def test_all_fleets_includes_each_additional_fleet(tmp_path):
    response = _client(tmp_path).get("/all")

    assert response.status_code == 200
    for line_name, count, _, _, _ in PROFILES.values():
        assert html.escape(line_name.upper()) in response.text
        assert f"Reporting: 0 / {count}" in response.text


def test_listener_union_contains_every_additional_mmsi():
    all_mmsis = {
        vessel.mmsi
        for vessel in load_fleet(profile="all").vessels
        if vessel.active and vessel.mmsi
    }

    assert len(all_mmsis) == 208
    for profile in PROFILES:
        profile_mmsis = {
            vessel.mmsi for vessel in load_fleet(profile=profile).vessels
        }
        assert profile_mmsis <= all_mmsis


@pytest.mark.parametrize("profile", PROFILES)
def test_search_finds_a_vessel_from_each_additional_fleet(profile):
    expected_fleet, _, _, _, query = PROFILES[profile]
    matches = search_vessels(load_fleet(profile="all"), query)

    assert any(vessel.cruise_line == expected_fleet for vessel in matches)


@pytest.mark.parametrize("profile", PROFILES)
def test_map_data_exposes_each_additional_fleet_identifier(profile):
    fleet = load_fleet(profile=profile)
    vessel = fleet.vessels[0]
    position = Position(
        vessel_name=vessel.name,
        latitude=50,
        longitude=-2,
        speed_knots=12,
        course_degrees=90,
        navigational_status="Under way",
        destination=None,
        reported_eta=None,
        position_timestamp=NOW,
        source="test",
    )

    dashboard = build_dashboard(
        load_fleet(profile="all"),
        {vessel.name.casefold(): position},
        NOW,
    )

    marker = next(item for item in dashboard["markers"] if item["name"] == vessel.name)
    assert marker["fleet"] == vessel.cruise_line


def test_fleet_page_map_contains_only_selected_profile(tmp_path):
    cache = PositionCache(tmp_path / "positions.sqlite3")
    for vessel_name in ("Norwegian Aqua", "Carnival Vista"):
        cache.update(
            Position(
                vessel_name=vessel_name,
                latitude=50,
                longitude=-2,
                speed_knots=12,
                course_degrees=90,
                navigational_status="Under way",
                destination=None,
                reported_eta=None,
                position_timestamp=NOW,
                source="test",
            )
        )

    response = TestClient(create_app(cache=cache, now_factory=lambda: NOW)).get("/ncl")
    match = re.search(
        r'<script id="fleet-map-data" type="application/json">(.*?)</script>',
        response.text,
        re.DOTALL,
    )

    assert match is not None
    markers = json.loads(match.group(1))
    assert {marker["name"] for marker in markers} == {"Norwegian Aqua"}


@pytest.mark.parametrize("field", ["mmsi", "imo"])
def test_duplicate_identifier_across_profiles_fails_validation(tmp_path, field):
    first = {"name": "Ship One", "imo": "9074729", "mmsi": "123456789"}
    second = {"name": "Ship Two", "imo": "9319466", "mmsi": "987654321"}
    second[field] = first[field]
    path = tmp_path / "fleet.yaml"
    path.write_text(
        json.dumps(
            {
                "cruise_lines": [
                    {"name": "Fleet One", "profile": "one", "vessels": [first]},
                    {"name": "Fleet Two", "profile": "two", "vessels": [second]},
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match=f"Duplicate {field.upper()}"):
        load_fleet(path, profile="all")

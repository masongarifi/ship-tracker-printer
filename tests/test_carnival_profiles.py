from datetime import datetime, timezone
import html

import pytest
from fastapi.testclient import TestClient

from fleet_receipt.cache import PositionCache
from fleet_receipt.config import load_fleet
from fleet_receipt.dashboard import (
    build_dashboard,
    exact_vessel_match,
    search_vessels,
)
from fleet_receipt.models import Position
from fleet_receipt.web import create_app


NOW = datetime(2026, 7, 23, 16, tzinfo=timezone.utc)
PROFILES = {
    "carnival": ("Carnival Cruise Line", 29, "Carnival Adventure"),
    "princess": ("Princess Cruises", 17, "Caribbean Princess"),
    "cunard": ("Cunard", 4, "Queen Anne"),
    "p-and-o": ("P&O Cruises", 7, "Arcadia"),
    "costa": ("Costa Cruises", 9, "Costa Deliziosa"),
    "aida": ("AIDA Cruises", 11, "AIDAbella"),
}


def _client(tmp_path):
    return TestClient(
        create_app(
            cache=PositionCache(tmp_path / "positions.sqlite3"),
            now_factory=lambda: NOW,
        )
    )


@pytest.mark.parametrize(
    ("profile", "expected"),
    [(profile, details[:2]) for profile, details in PROFILES.items()],
)
def test_new_profiles_load(profile, expected):
    line_name, count = expected
    fleet = load_fleet(profile=profile)

    assert fleet.cruise_line_order == (line_name,)
    assert len(fleet.vessels) == count
    assert all(vessel.active for vessel in fleet.vessels)


def test_all_identifiers_are_valid_and_unique_across_fleets():
    vessels = load_fleet(profile="all").vessels
    mmsis = [vessel.mmsi for vessel in vessels]
    imos = [vessel.imo for vessel in vessels]

    assert len(vessels) == 138
    assert len(set(mmsis)) == len(mmsis)
    assert len(set(imos)) == len(imos)
    assert all(value and len(value) == 9 and value.isdigit() for value in mmsis)
    assert all(value and len(value) == 7 and value.isdigit() for value in imos)


@pytest.mark.parametrize("profile", PROFILES)
def test_new_fleet_and_profile_routes_render(profile, tmp_path):
    client = _client(tmp_path)

    for route in (f"/{profile}", f"/profile/{profile}"):
        response = client.get(route)
        assert response.status_code == 200
        assert html.escape(PROFILES[profile][0]) in response.text
        assert "← Fleet Tracker Home" in response.text


def test_homepage_cards_and_totals_include_new_fleets(tmp_path):
    response = _client(tmp_path).get("/")

    assert response.status_code == 200
    for profile, (line_name, count, _) in PROFILES.items():
        assert f'href="http://testserver/{profile}"' in response.text
        assert html.escape(line_name.split()[0]) in response.text
        assert f"{count} ships" in response.text
    assert "138" in response.text


def test_all_fleets_report_groups_new_brands(tmp_path):
    response = _client(tmp_path).get("/all")

    assert response.status_code == 200
    for line_name, count, _ in PROFILES.values():
        assert f"Reporting: 0 / {count}" in response.text
        assert html.escape(line_name.upper()) in response.text


@pytest.mark.parametrize(
    ("query", "expected_name"),
    [
        ("Carnival Adventure", "Carnival Adventure"),
        ("Discovery Princess", "Discovery Princess"),
        ("QM2", "Queen Mary 2"),
        ("ARVIA", "Arvia"),
        ("COSTA TOSCANA", "Costa Toscana"),
        ("AIDACOSMA", "AIDAcosma"),
        ("311001595", "Carnival Adventure"),
        ("9863120", "Star Princess"),
    ],
)
def test_search_finds_new_ships_by_name_alias_and_identifier(query, expected_name):
    matches = search_vessels(load_fleet(profile="all"), query)

    assert expected_name in {vessel.name for vessel in matches}


@pytest.mark.parametrize(
    ("ship_name", "fleet_name"),
    [
        ("Carnival Adventure", "Carnival Cruise Line"),
        ("Discovery Princess", "Princess Cruises"),
        ("Queen Anne", "Cunard"),
        ("Arvia", "P&O Cruises"),
        ("Costa Toscana", "Costa Cruises"),
        ("AIDAcosma", "AIDA Cruises"),
    ],
)
def test_map_data_uses_new_fleet_identifiers(ship_name, fleet_name):
    fleet = load_fleet(profile="all")
    positions = {
        ship_name.casefold(): Position(
            vessel_name=ship_name,
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
    }

    markers = build_dashboard(fleet, positions, NOW)["markers"]

    assert markers[0]["fleet"] == fleet_name


def test_aliases_are_stored_separately_from_official_names():
    fleet = load_fleet(profile="carnival")
    adventure = next(
        vessel for vessel in fleet.vessels if vessel.name == "Carnival Adventure"
    )

    assert adventure.name == "Carnival Adventure"
    assert "Pacific Adventure" in adventure.aliases
    assert "Golden Princess" in adventure.aliases


def test_official_name_wins_when_it_matches_another_vessels_former_name():
    matches = search_vessels(load_fleet(profile="all"), "Star Princess")

    assert exact_vessel_match(matches, "Star Princess").name == "Star Princess"

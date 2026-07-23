from datetime import datetime, timedelta, timezone

from fleet_receipt.config import load_fleet
from fleet_receipt.dashboard import build_dashboard, search_vessels, vessel_slug
from fleet_receipt.models import Position


NOW = datetime(2026, 7, 23, 16, 0, tzinfo=timezone.utc)


def _position(
    name: str,
    *,
    latitude: float,
    speed: float,
    status: str,
    minutes_old: int,
) -> Position:
    return Position(
        vessel_name=name,
        latitude=latitude,
        longitude=-122.3,
        speed_knots=speed,
        course_degrees=90,
        navigational_status=status,
        destination=None,
        reported_eta=None,
        position_timestamp=NOW - timedelta(minutes=minutes_old),
        source="AISstream.io",
    )


def test_dashboard_summarizes_fleets_and_spotlights_from_cache() -> None:
    fleet = load_fleet(profile="all")
    positions = {
        "koningsdam": _position(
            "Koningsdam",
            latitude=55,
            speed=18.2,
            status="Under way",
            minutes_old=1,
        ),
        "celebrity apex": _position(
            "Celebrity Apex",
            latitude=-20,
            speed=0,
            status="Moored",
            minutes_old=5,
        ),
    }

    dashboard = build_dashboard(fleet, positions, NOW)
    cards = {card["slug"]: card for card in dashboard["fleet_cards"]}
    spotlights = {item["label"]: item["value"] for item in dashboard["spotlights"]}

    assert cards["hal"]["total"] == 11
    assert cards["hal"]["underway"] == 1
    assert cards["celebrity"]["total"] == 15
    assert cards["celebrity"]["moored"] == 1
    assert dashboard["statistics"][0]["value"] == 61
    assert dashboard["statistics"][1]["value"] == 1
    assert dashboard["statistics"][2]["value"] == 1
    assert dashboard["statistics"][3]["value"] == "1 minute ago"
    assert spotlights["Fastest ship"] == "Koningsdam · 18.2 kt"
    assert spotlights["Northernmost ship"] == "Koningsdam"
    assert spotlights["Southernmost ship"] == "Celebrity Apex"
    assert spotlights["Longest underway"] == "Unavailable"
    assert dashboard["recent_changes"] == ()


def test_search_supports_name_imo_and_mmsi() -> None:
    fleet = load_fleet(profile="all")

    assert [vessel.name for vessel in search_vessels(fleet, "Konings")] == [
        "Koningsdam"
    ]
    assert [vessel.name for vessel in search_vessels(fleet, "9692557")] == [
        "Koningsdam"
    ]
    assert [vessel.name for vessel in search_vessels(fleet, "244830547")] == [
        "Koningsdam"
    ]
    assert vessel_slug("Adventure of the Seas") == "adventure-of-the-seas"

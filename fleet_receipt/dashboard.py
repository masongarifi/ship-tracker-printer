import re
from datetime import datetime, timezone
from typing import Dict, Iterable, Optional

from .ais_status import navigational_status
from .formatting_helpers import format_destination, format_eta, format_position_age
from .locations import format_coordinates
from .models import FleetData, Position, Vessel

FLEET_PROFILES = (
    {
        "slug": "hal",
        "name": "Holland America",
        "config_name": "Holland America Line",
        "mark": "HAL",
    },
    {
        "slug": "seabourn",
        "name": "Seabourn",
        "config_name": "Seabourn",
        "mark": "SBN",
    },
    {
        "slug": "celebrity",
        "name": "Celebrity",
        "config_name": "Celebrity Cruises",
        "mark": "CEL",
    },
    {
        "slug": "royal-caribbean",
        "name": "Royal Caribbean",
        "config_name": "Royal Caribbean International",
        "mark": "RCI",
    },
)


def build_dashboard(
    fleet: FleetData,
    positions: Dict[str, Position],
    generated_at: datetime,
) -> Dict[str, object]:
    active = [vessel for vessel in fleet.vessels if vessel.active]
    configured_names = {vessel.name.casefold() for vessel in active}
    known_positions = {
        key: position
        for key, position in positions.items()
        if key in configured_names
    }
    vessel_by_name = {vessel.name.casefold(): vessel for vessel in active}

    fleet_cards = []
    for profile in FLEET_PROFILES:
        vessels = [
            vessel
            for vessel in active
            if vessel.cruise_line == profile["config_name"]
        ]
        profile_positions = [
            known_positions[vessel.name.casefold()]
            for vessel in vessels
            if vessel.name.casefold() in known_positions
        ]
        fleet_cards.append(
            {
                **profile,
                "total": len(vessels),
                "underway": sum(_is_underway(position) for position in profile_positions),
                "moored": sum(_is_moored(position) for position in profile_positions),
            }
        )

    markers = [
        _marker(vessel_by_name[key], position)
        for key, position in known_positions.items()
        if _valid_map_position(position)
    ]
    newest = max(
        (position.position_timestamp for position in known_positions.values()),
        default=None,
    )
    underway_count = sum(_is_underway(position) for position in known_positions.values())
    moored_count = sum(_is_moored(position) for position in known_positions.values())

    return {
        "fleet_cards": fleet_cards,
        "markers": markers,
        "statistics": (
            {"label": "Total ships", "value": len(active)},
            {"label": "Ships underway", "value": underway_count},
            {"label": "Ships moored", "value": moored_count},
            {
                "label": "Last AIS update",
                "value": _age(newest, generated_at),
            },
        ),
        "spotlights": _spotlights(known_positions),
        "recent_changes": (),
        "cached_ship_count": len(known_positions),
    }


def search_vessels(fleet: FleetData, query: str) -> list[Vessel]:
    needle = query.strip().casefold()
    if not needle:
        return []
    matches = [
        vessel
        for vessel in fleet.vessels
        if vessel.active
        and any(
            needle in candidate.casefold()
            for candidate in (vessel.name, vessel.imo or "", vessel.mmsi or "")
        )
    ]
    return sorted(matches, key=lambda vessel: vessel.name.casefold())


def exact_vessel_match(vessels: Iterable[Vessel], query: str) -> Optional[Vessel]:
    needle = query.strip().casefold()
    for vessel in vessels:
        if needle in {
            vessel.name.casefold(),
            (vessel.imo or "").casefold(),
            (vessel.mmsi or "").casefold(),
        }:
            return vessel
    return None


def vessel_for_slug(fleet: FleetData, slug: str) -> Optional[Vessel]:
    return next(
        (
            vessel
            for vessel in fleet.vessels
            if vessel.active and vessel_slug(vessel.name) == slug
        ),
        None,
    )


def build_ship_detail(
    vessel: Vessel,
    position: Optional[Position],
    generated_at: datetime,
) -> Dict[str, object]:
    details = {
        "name": vessel.name,
        "fleet": vessel.cruise_line,
        "imo": vessel.imo or "Unavailable",
        "mmsi": vessel.mmsi or "Unavailable",
        "position_available": position is not None,
    }
    if position is None:
        return details
    details.update(
        {
            "status": _status(position),
            "speed": _speed(position),
            "course": _course(position),
            "destination": format_destination(position.destination) or "Unavailable",
            "eta": format_eta(position.reported_eta) or "Unavailable",
            "coordinates": format_coordinates(position.latitude, position.longitude),
            "updated": _age(position.position_timestamp, generated_at),
        }
    )
    return details


def vessel_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")


def _marker(vessel: Vessel, position: Position) -> Dict[str, object]:
    return {
        "name": vessel.name,
        "fleet": vessel.cruise_line,
        "status": _status(position),
        "speed": _speed(position),
        "course": _course(position),
        "destination": format_destination(position.destination) or "Unavailable",
        "eta": format_eta(position.reported_eta) or "Unavailable",
        "latitude": position.latitude,
        "longitude": position.longitude,
        "details_url": f"/ship/{vessel_slug(vessel.name)}",
    }


def _spotlights(positions: Dict[str, Position]) -> tuple[Dict[str, str], ...]:
    available = list(positions.values())
    fastest = max(
        (
            position
            for position in available
            if isinstance(position.speed_knots, (int, float))
            and position.speed_knots >= 0
        ),
        key=lambda position: position.speed_knots,
        default=None,
    )
    northern = max(available, key=lambda position: position.latitude, default=None)
    southern = min(available, key=lambda position: position.latitude, default=None)
    return (
        {
            "label": "Fastest ship",
            "value": (
                f"{fastest.vessel_name} · {fastest.speed_knots:.1f} kt"
                if fastest
                else "Unavailable"
            ),
        },
        {
            "label": "Northernmost ship",
            "value": northern.vessel_name if northern else "Unavailable",
        },
        {
            "label": "Southernmost ship",
            "value": southern.vessel_name if southern else "Unavailable",
        },
        {"label": "Longest underway", "value": "Unavailable"},
        {"label": "Most recent departure", "value": "Unavailable"},
        {"label": "Most recent arrival", "value": "Unavailable"},
    )


def _status(position: Position) -> str:
    value = navigational_status(position.navigational_status)
    return "Underway" if _is_underway(position) else value


def _is_underway(position: Position) -> bool:
    normalized = navigational_status(position.navigational_status)
    return normalized.casefold().replace(" ", "").startswith("underway")


def _is_moored(position: Position) -> bool:
    return navigational_status(position.navigational_status).casefold() == "moored"


def _speed(position: Position) -> str:
    value = position.speed_knots
    return f"{value:.1f} kt" if isinstance(value, (int, float)) and value >= 0 else "Unavailable"


def _course(position: Position) -> str:
    value = position.course_degrees
    if not isinstance(value, (int, float)) or not 0 <= value < 360:
        return "Unavailable"
    return f"{round(value) % 360:03d}°"


def _valid_map_position(position: Position) -> bool:
    latitude = position.latitude
    longitude = position.longitude
    return (
        isinstance(latitude, (int, float))
        and isinstance(longitude, (int, float))
        and -90 <= latitude <= 90
        and -180 <= longitude <= 180
    )


def _age(value: Optional[datetime], generated_at: datetime) -> str:
    if value is None:
        return "Unavailable"
    aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    age, _ = format_position_age(aware, generated_at, float("inf"))
    return f"{age} ago"

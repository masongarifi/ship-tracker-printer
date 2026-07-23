import re
from datetime import datetime, timezone
from typing import Dict, Iterable, Optional

from .ais_status import is_underway_status, navigational_status
from .formatting_helpers import format_destination, format_eta, format_position_age
from .locations import format_coordinates
from .models import FleetData, Position, Vessel

FLEET_PROFILES = (
    {
        "slug": "hal",
        "name": "Holland America",
        "config_name": "Holland America Line",
        "mark": "HAL",
        "route_name": "hal_page",
    },
    {
        "slug": "seabourn",
        "name": "Seabourn",
        "config_name": "Seabourn",
        "mark": "SBN",
        "route_name": "seabourn_page",
    },
    {
        "slug": "celebrity",
        "name": "Celebrity",
        "config_name": "Celebrity Cruises",
        "mark": "CEL",
        "route_name": "celebrity_page",
    },
    {
        "slug": "royal-caribbean",
        "name": "Royal Caribbean",
        "config_name": "Royal Caribbean International",
        "mark": "RCI",
        "route_name": "royal_caribbean_page",
    },
    {
        "slug": "carnival",
        "name": "Carnival",
        "config_name": "Carnival Cruise Line",
        "mark": "CCL",
        "route_name": "carnival_page",
    },
    {
        "slug": "princess",
        "name": "Princess",
        "config_name": "Princess Cruises",
        "mark": "PCL",
        "route_name": "princess_page",
    },
    {
        "slug": "cunard",
        "name": "Cunard",
        "config_name": "Cunard",
        "mark": "CUN",
        "route_name": "cunard_page",
    },
    {
        "slug": "p-and-o",
        "name": "P&O Cruises",
        "config_name": "P&O Cruises",
        "mark": "P&O",
        "route_name": "p_and_o_page",
    },
    {
        "slug": "costa",
        "name": "Costa",
        "config_name": "Costa Cruises",
        "mark": "COS",
        "route_name": "costa_page",
    },
    {
        "slug": "aida",
        "name": "AIDA",
        "config_name": "AIDA Cruises",
        "mark": "AIDA",
        "route_name": "aida_page",
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
                "reporting": len(profile_positions),
                "unavailable": len(vessels) - len(profile_positions),
                "underway": sum(_is_underway(position) for position in profile_positions),
                "moored": sum(
                    _is_moored_or_anchored(position)
                    for position in profile_positions
                ),
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
    moored_count = sum(
        _is_moored_or_anchored(position)
        for position in known_positions.values()
    )

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
        "spotlights": _spotlights(known_positions, generated_at),
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
            for candidate in (
                vessel.name,
                vessel.imo or "",
                vessel.mmsi or "",
                *vessel.aliases,
            )
        )
    ]
    return sorted(matches, key=lambda vessel: vessel.name.casefold())


def exact_vessel_match(vessels: Iterable[Vessel], query: str) -> Optional[Vessel]:
    needle = query.strip().casefold()
    candidates = list(vessels)
    for vessel in candidates:
        if needle in {
            vessel.name.casefold(),
            (vessel.imo or "").casefold(),
            (vessel.mmsi or "").casefold(),
        }:
            return vessel
    for vessel in candidates:
        if needle in {alias.casefold() for alias in vessel.aliases}:
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


def _spotlights(
    positions: Dict[str, Position], generated_at: datetime
) -> tuple[Dict[str, str], ...]:
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
    longest_underway = _longest_underway(available, generated_at)
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
        {"label": "Longest underway", "value": longest_underway},
        {"label": "Most recent departure", "value": "Unavailable"},
        {"label": "Most recent arrival", "value": "Unavailable"},
    )


def _status(position: Position) -> str:
    value = navigational_status(position.navigational_status)
    return "Underway" if _is_underway(position) else value


def _is_underway(position: Position) -> bool:
    return is_underway_status(position.navigational_status)


def _is_moored_or_anchored(position: Position) -> bool:
    normalized = navigational_status(position.navigational_status).casefold()
    return normalized in {"moored", "at anchor", "anchored"}


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


def _longest_underway(
    positions: Iterable[Position], generated_at: datetime
) -> str:
    now = _aware_utc(generated_at)
    candidates = []
    for position in positions:
        started = position.underway_since
        if not _is_underway(position) or not isinstance(started, datetime):
            continue
        started_utc = _aware_utc(started)
        if started_utc > now:
            continue
        candidates.append((now - started_utc, position.vessel_name))
    if not candidates:
        return "Unavailable"
    duration, vessel_name = max(candidates, key=lambda candidate: candidate[0])
    return f"{vessel_name} · {_format_underway_duration(duration)}"


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _format_underway_duration(duration) -> str:
    total_hours = max(0, int(duration.total_seconds() // 3600))
    days, hours = divmod(total_hours, 24)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h"
    return "<1h"

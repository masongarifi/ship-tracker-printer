from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Mapping, Optional, Tuple

from .ais_status import navigational_status
from .formatting_helpers import (
    format_course,
    format_eta,
    format_position_age,
    format_seattle_offset,
    should_show_course,
    should_show_speed,
)
from .locations import (
    format_coordinates,
    get_friendly_location,
    get_nearest_landmark,
    resolve_location,
)
from .models import FleetData, Position, Vessel
from .timezones import estimate_local_time


@dataclass(frozen=True)
class VesselBrief:
    name: str
    location: str
    landmark: Optional[str]
    coordinates: str
    status: str
    speed: Optional[str]
    course: Optional[str]
    destination: Optional[str]
    eta: Optional[str]
    utc_time: str
    local_time: str
    age_heading: str
    age: str


@dataclass(frozen=True)
class FleetBriefing:
    summary: Tuple[str, ...]
    source: str
    vessels: Tuple[VesselBrief, ...]
    missing_names: Tuple[str, ...]
    missing_reason: str


def build_fleet_briefing(
    fleet: FleetData,
    positions: Dict[str, Position],
    generated_at: datetime,
    stale_after_hours: float,
    feed_health: Optional[Mapping[str, object]] = None,
) -> FleetBriefing:
    active = [vessel for vessel in fleet.vessels if vessel.active]
    summary = []
    for line_name in fleet.cruise_line_order:
        line_vessels = [vessel for vessel in active if vessel.cruise_line == line_name]
        reporting = sum(vessel.name.casefold() in positions for vessel in line_vessels)
        summary.append(
            f"{_line_label(line_name)} Reporting: {reporting} / {len(line_vessels)}"
        )

    briefs: List[VesselBrief] = []
    missing = []
    for vessel in _sorted_vessels(fleet, active):
        position = positions.get(vessel.name.casefold())
        if position is None:
            missing.append(vessel.name.upper())
        else:
            briefs.append(
                build_vessel_brief(
                    vessel, position, generated_at, stale_after_hours
                )
            )

    health = dict(feed_health or {})
    source = str(health.get("source") or "Terrestrial")
    return FleetBriefing(
        tuple(summary),
        source,
        tuple(briefs),
        tuple(missing),
        _missing_reason(health, source),
    )


def build_vessel_brief(
    vessel: Vessel,
    position: Position,
    generated_at: datetime,
    stale_after_hours: float,
) -> VesselBrief:
    location = get_friendly_location(position.latitude, position.longitude)
    landmark = get_nearest_landmark(position.latitude, position.longitude)
    if (
        landmark
        and not location.startswith("Port of ")
        and any(part in location for part in _landmark_names(landmark))
    ):
        landmark = None

    estimate = estimate_local_time(position, resolve_location(position))
    age, stale = format_position_age(
        position.position_timestamp, generated_at, stale_after_hours
    )
    status = navigational_status(position.navigational_status)
    if status.casefold() == "under way":
        status = "Underway"
    is_underway = status.casefold().replace(" ", "").startswith("underway")
    destination = (
        position.destination.strip().upper()
        if is_underway and position.destination
        else None
    )
    return VesselBrief(
        name=vessel.name.upper(),
        location=location,
        landmark=landmark,
        coordinates=format_coordinates(position.latitude, position.longitude),
        status=status.upper(),
        speed=(
            f"{position.speed_knots:.1f} kt"
            if should_show_speed(status, position.speed_knots)
            else None
        ),
        course=(
            format_course(position.course_degrees)
            if should_show_course(
                status, position.speed_knots, position.course_degrees
            )
            else None
        ),
        destination=destination,
        eta=format_eta(position.reported_eta) if destination else None,
        utc_time=position.position_timestamp.astimezone(timezone.utc).strftime("%H:%M"),
        local_time=(
            f"{estimate.local_time:%H:%M} "
            f"{format_seattle_offset(estimate.offset_minutes)}"
        ),
        age_heading="Last AIS report" if stale else "Updated",
        age=f"{age} ago",
    )


def _sorted_vessels(fleet: FleetData, vessels: List[Vessel]) -> List[Vessel]:
    line_index = {name: index for index, name in enumerate(fleet.cruise_line_order)}
    return sorted(
        vessels,
        key=lambda vessel: (
            line_index.get(vessel.cruise_line, len(line_index)),
            vessel.name.casefold(),
        ),
    )


def _line_label(name: str) -> str:
    if name.casefold() == "holland america line":
        return "HAL"
    return name


def _missing_reason(health: Mapping[str, object], source: str) -> str:
    status = str(health.get("status") or "unknown").casefold()
    error = health.get("error")
    if status == "error" and error:
        return f"AIS feed error: {error}"
    if status in {"connecting", "timeout"}:
        return "AIS feed is connecting or timed out."
    if source.casefold() == "terrestrial":
        return "Likely outside terrestrial AIS coverage."
    return "No position has been received from the AIS source."


def _landmark_names(value: str) -> Tuple[str, ...]:
    tail = value.split(" of ", 1)[-1].removeprefix("Near ")
    return tuple(part.strip() for part in tail.split(",") if part.strip())

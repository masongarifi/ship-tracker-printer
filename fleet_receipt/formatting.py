import textwrap
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Mapping, Optional

from .briefing import build_fleet_briefing
from .feed_status import is_feed_offline
from .formatting_helpers import format_position_age
from .models import FleetData, Position, Vessel

OFFLINE_BANNER = "*****AISStream.io OFFLINE*****"


def sorted_active_vessels(fleet: FleetData) -> List[Vessel]:
    line_index = {name: index for index, name in enumerate(fleet.cruise_line_order)}
    return sorted(
        (vessel for vessel in fleet.vessels if vessel.active),
        key=lambda vessel: (
            line_index.get(vessel.cruise_line, len(line_index)),
            vessel.name.casefold(),
        ),
    )


def format_receipt(
    fleet: FleetData,
    positions: Dict[str, Position],
    generated_at: datetime,
    width: int = 42,
    stale_after_hours: float = 6,
    feed_health: Optional[Mapping[str, object]] = None,
    group_by_fleet: bool = False,
    show_offline_banner: bool = False,
) -> str:
    if generated_at.tzinfo is None:
        raise ValueError("Report time must be timezone-aware")
    briefing = build_fleet_briefing(
        fleet, positions, generated_at, stale_after_hours, feed_health
    )
    lines: List[str] = []
    if show_offline_banner and is_feed_offline(positions, generated_at):
        lines.extend([OFFLINE_BANNER, ""])
    lines.extend(["FLEET OPERATIONS BRIEF", _report_timestamp(generated_at)])
    lines.extend(briefing.summary)
    lines.extend([f"AIS Source: {briefing.source}", "═" * width])

    line_by_vessel = {
        vessel.name.upper(): vessel.cruise_line
        for vessel in fleet.vessels
        if vessel.active
    }
    current_line = None
    for vessel in briefing.vessels:
        vessel_line = line_by_vessel.get(vessel.name)
        if group_by_fleet and vessel_line != current_line:
            _append_fleet_heading(lines, vessel_line or "Other", width)
            current_line = vessel_line
        _append_single_blank_line(lines)
        lines.extend([vessel.name, "─" * min(len(vessel.name), width)])
        _append_wrapped(lines, vessel.location, width)
        if vessel.landmark:
            _append_wrapped(lines, vessel.landmark, width)
        _append_coordinate(lines, vessel.coordinates, width)

        _append_wrapped(lines, vessel.movement, width)
        if vessel.voyage:
            for voyage_line in vessel.voyage.splitlines():
                _append_wrapped(lines, voyage_line, width)
        lines.extend([f"UTC {vessel.utc_time}", f"Local {vessel.local_time}"])
        lines.append(f"{vessel.age_heading} {vessel.age}")

    if briefing.missing_names:
        lines.extend(
            [
                "",
                "─" * min(16, width),
                f"NO RECENT AIS ({len(briefing.missing_names)})",
            ]
        )
        if group_by_fleet:
            for line_name in fleet.cruise_line_order:
                line_missing = [
                    name
                    for name in briefing.missing_names
                    if line_by_vessel.get(name) == line_name
                ]
                if line_missing:
                    lines.extend([line_name.upper(), *line_missing])
        else:
            lines.extend(briefing.missing_names)
        _append_wrapped(lines, briefing.missing_reason, width)

    lines.extend(["Latest available AIS positions", "Times are estimated"])
    return "\n".join(_wrap_existing(lines, width)).rstrip() + "\n"


def format_age(seconds: float) -> str:
    origin = datetime(1970, 1, 1, tzinfo=timezone.utc)
    generated = origin + timedelta(seconds=seconds)
    return format_position_age(origin, generated, float("inf"))[0]


def _append_coordinate(lines: List[str], value: str, width: int) -> None:
    if len(value) <= width:
        lines.append(value)
        return
    latitude, longitude = value.split(" ", 1)
    lines.extend((latitude, longitude))


def _report_timestamp(value: datetime) -> str:
    from zoneinfo import ZoneInfo

    seattle = value.astimezone(ZoneInfo("America/Los_Angeles"))
    return f"{seattle:%Y-%m-%d %H:%M} Seattle"


def _append_wrapped(lines: List[str], value: str, width: int) -> None:
    lines.extend(
        textwrap.wrap(
            value, width=width, break_long_words=False, break_on_hyphens=False
        )
        or [""]
    )


def _append_fleet_heading(lines: List[str], name: str, width: int) -> None:
    lines.extend(["", name.upper(), "=" * min(len(name), width)])


def _append_single_blank_line(lines: List[str]) -> None:
    """Separate sections with exactly one blank line."""
    while lines and lines[-1] == "":
        lines.pop()
    lines.append("")


def _wrap_existing(lines: Iterable[str], width: int) -> Iterable[str]:
    for line in lines:
        if len(line) <= width:
            yield line
        else:
            yield from textwrap.wrap(
                line, width=width, break_long_words=False, break_on_hyphens=False
            )

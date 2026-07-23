from datetime import timedelta, timezone
from zoneinfo import ZoneInfo

from .models import Location, Position, TimeEstimate


def estimate_local_time(
    position: Position,
    location: Location,
    seattle_timezone: str = "America/Los_Angeles",
) -> TimeEstimate:
    instant = position.position_timestamp
    if instant.tzinfo is None:
        raise ValueError("Position timestamp must be timezone-aware")
    seattle = instant.astimezone(ZoneInfo(seattle_timezone))
    timezone_name = location.timezone_name or _coordinate_timezone(position)
    approximate = location.timezone_name is None
    if approximate:
        offset = nautical_offset_hours(position.longitude)
        local = instant.astimezone(timezone(timedelta(hours=offset)))
        label = f"nautical UTC{offset:+d}"
    else:
        local = instant.astimezone(ZoneInfo(timezone_name))
        label = timezone_name
    local_offset = local.utcoffset() or timedelta(0)
    seattle_offset = seattle.utcoffset() or timedelta(0)
    difference = int((local_offset - seattle_offset).total_seconds() // 60)
    return TimeEstimate(local, seattle, difference, label, approximate)


def _coordinate_timezone(position: Position):
    # An optional global offline lookup can be added without changing callers.
    return None


def nautical_offset_hours(longitude: float) -> int:
    offset = int(math_floor_half_away(longitude / 15.0))
    return max(-12, min(14, offset))


def math_floor_half_away(value: float) -> int:
    return int(value + 0.5) if value >= 0 else int(value - 0.5)


def relative_to_seattle(minutes: int) -> str:
    if minutes == 0:
        return "Same time as Seattle"
    direction = "ahead of" if minutes > 0 else "behind"
    total = abs(minutes)
    hours, remainder = divmod(total, 60)
    parts = []
    if hours:
        parts.append(f"{hours} hour" + ("" if hours == 1 else "s"))
    if remainder:
        parts.append(f"{remainder} minute" + ("" if remainder == 1 else "s"))
    return f"{' '.join(parts)} {direction} Seattle"


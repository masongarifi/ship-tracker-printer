from datetime import datetime, timezone
from typing import Optional, Tuple


def should_show_speed(status: str, speed: Optional[float]) -> bool:
    return not _stationary_status(status) and _valid_number(speed) and speed >= 0


def should_show_course(
    status: str, speed: Optional[float], course: Optional[float]
) -> bool:
    return (
        not _stationary_status(status)
        and _valid_number(speed)
        and speed >= 0
        and _valid_number(course)
        and 0 <= course < 360
    )


def format_course(value: Optional[float]) -> Optional[str]:
    if value is None or not (0 <= value < 360):
        return None
    return f"Course {round(value) % 360:03d}°"


def format_eta(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return f"ETA {parsed.day:02d} {parsed:%b} {parsed:%H%M}"
    except ValueError:
        return f"ETA {value.strip()}" if value.strip() else None


def format_position_age(
    reported_at: datetime,
    generated_at: datetime,
    stale_after_hours: float,
) -> Tuple[str, bool]:
    seconds = max(
        0,
        (
            generated_at.astimezone(timezone.utc)
            - reported_at.astimezone(timezone.utc)
        ).total_seconds(),
    )
    minutes = int(seconds // 60)
    if minutes < 1:
        age = "<1 minute"
    elif minutes < 60:
        age = f"{minutes} minute" + ("" if minutes == 1 else "s")
    else:
        hours = minutes // 60
        if hours < 24:
            age = f"{hours} hour" + ("" if hours == 1 else "s")
        else:
            days = hours // 24
            age = f"{days} day" + ("" if days == 1 else "s")
    return age, seconds >= stale_after_hours * 3600


def format_seattle_offset(minutes: int) -> str:
    if minutes == 0:
        return "(Same as Seattle)"
    sign = "+" if minutes > 0 else "-"
    total = abs(minutes)
    hours, remainder = divmod(total, 60)
    value = f"{hours}" if remainder == 0 else f"{hours}:{remainder:02d}"
    return f"({sign}{value} Seattle)"


def _stationary_status(status: str) -> bool:
    normalized = " ".join(status.strip().casefold().split())
    return normalized in {"moored", "at anchor", "anchored"}


def _valid_number(value: Optional[float]) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)

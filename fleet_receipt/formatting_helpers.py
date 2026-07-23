from datetime import datetime, timezone
import re
from typing import Optional, Tuple

from .unlocode import lookup_unlocode

# Add new UN/LOCODE entries here. Keys are canonical two-letter country code
# plus three-letter location code; input with or without spaces is accepted.
UNLOCODE_PORTS = {
    "GB DVR": "Dover, United Kingdom",
    "GB SOU": "Southampton, United Kingdom",
    "NL RTM": "Rotterdam, Netherlands",
    "BE ANR": "Antwerp, Belgium",
    "DE HAM": "Hamburg, Germany",
    "FR LEH": "Le Havre, France",
    "US SEA": "Seattle, Washington",
    "US LAX": "Los Angeles, California",
    "CA VAN": "Vancouver, British Columbia",
    "SG SIN": "Singapore",
    "IS REY": "Reykjavik, Iceland",
}


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
        return f"ETA {parsed.day:02d} {parsed:%b} {parsed:%H%M} UTC"
    except ValueError:
        cleaned = value.strip()
        if not cleaned:
            return None
        return f"ETA {cleaned}" + ("" if cleaned.upper().endswith("UTC") else " UTC")


def format_destination(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = " ".join(value.strip(" @").split())
    if not cleaned:
        return None
    endpoints = re.split(r"\s*(?:->|>|→)\s*", cleaned, maxsplit=1)
    if len(endpoints) == 2 and all(endpoints):
        return f"{_friendly_endpoint(endpoints[0])} → {_friendly_endpoint(endpoints[1])}"
    return _friendly_endpoint(cleaned)


def format_movement(
    status: str, speed: Optional[float], course: Optional[float]
) -> str:
    normalized = " ".join(status.strip().upper().split())
    parts = [normalized]
    if should_show_course(status, speed, course):
        parts.append(f"CRS {round(course) % 360:03d}°")
    if should_show_speed(status, speed):
        parts.append(f"at {speed:.1f} kts")
    return " ".join(parts)


def format_voyage(destination: Optional[str], eta: Optional[str]) -> Optional[str]:
    friendly = format_destination(destination)
    if not friendly:
        return None
    destination_line = friendly if " → " in friendly else f"Destination {friendly}"
    return destination_line + (f"\n{eta}" if eta else "")


def _friendly_endpoint(value: str) -> str:
    cleaned = " ".join(value.strip(" @").split())
    compact = re.sub(r"[\s-]+", "", cleaned).upper()
    canonical = f"{compact[:2]} {compact[2:]}" if len(compact) == 5 else ""
    return (
        lookup_unlocode(canonical)
        or UNLOCODE_PORTS.get(canonical)
        or cleaned.title()
    )


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

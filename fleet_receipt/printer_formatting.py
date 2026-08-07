import re
import textwrap
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone
from typing import Dict, Iterable, Mapping, Optional, Sequence

from .ais_status import is_underway_status, navigational_status
from .briefing import FleetBriefing, VesselBrief, build_fleet_briefing
from .cache import PositionCache
from .config import load_fleet, load_settings
from .feed_status import is_feed_offline
from .formatting import OFFLINE_BANNER, format_receipt
from .models import FleetData, Position

FONT_A = "a"
FONT_B = "b"
COLUMN_GAP = 4
# The TM-L90's Font B row is kept two characters below its nominal maximum.
# This accounts for the printer's active printable area and prevents the
# firmware from wrapping the completed left/right row.
FONT_B_PRINTABLE_WIDTH = 54
CARNIVAL_CORPORATION_LINES = {
    "Carnival Cruise Line",
    "Princess Cruises",
    "Cunard",
    "P&O Cruises",
    "Costa Cruises",
    "AIDA Cruises",
}
US_STATE_ABBREVIATIONS = {
    "Alabama": "AL",
    "Alaska": "AK",
    "Arizona": "AZ",
    "Arkansas": "AR",
    "California": "CA",
    "Colorado": "CO",
    "Connecticut": "CT",
    "Delaware": "DE",
    "Florida": "FL",
    "Georgia": "GA",
    "Hawaii": "HI",
    "Idaho": "ID",
    "Illinois": "IL",
    "Indiana": "IN",
    "Iowa": "IA",
    "Kansas": "KS",
    "Kentucky": "KY",
    "Louisiana": "LA",
    "Maine": "ME",
    "Maryland": "MD",
    "Massachusetts": "MA",
    "Michigan": "MI",
    "Minnesota": "MN",
    "Mississippi": "MS",
    "Missouri": "MO",
    "Montana": "MT",
    "Nebraska": "NE",
    "Nevada": "NV",
    "New Hampshire": "NH",
    "New Jersey": "NJ",
    "New Mexico": "NM",
    "New York": "NY",
    "North Carolina": "NC",
    "North Dakota": "ND",
    "Ohio": "OH",
    "Oklahoma": "OK",
    "Oregon": "OR",
    "Pennsylvania": "PA",
    "Rhode Island": "RI",
    "South Carolina": "SC",
    "South Dakota": "SD",
    "Tennessee": "TN",
    "Texas": "TX",
    "Utah": "UT",
    "Vermont": "VT",
    "Virginia": "VA",
    "Washington": "WA",
    "West Virginia": "WV",
    "Wisconsin": "WI",
    "Wyoming": "WY",
}


@dataclass(frozen=True)
class ReceiptSegment:
    font: str
    text: str
    emphasized: bool = False


@dataclass(frozen=True)
class PrinterReceipt:
    """Printable text plus Epson font choices that do not appear in previews."""

    segments: tuple[ReceiptSegment, ...]

    @property
    def text(self) -> str:
        return "".join(segment.text for segment in self.segments)


def format_printer_receipt(
    fleet: FleetData,
    positions: Dict[str, Position],
    generated_at: datetime,
    width: int = 42,
    stale_after_hours: float = 6,
    feed_health: Optional[Mapping[str, object]] = None,
    group_by_fleet: bool = False,
    two_column: bool = True,
    show_offline_banner: bool = False,
) -> PrinterReceipt:
    """Format CLI/thermal output without changing the web receipt formatter."""
    if not two_column:
        return PrinterReceipt(
            (
                ReceiptSegment(
                    FONT_A,
                    format_receipt(
                        fleet,
                        positions,
                        generated_at,
                        width=width,
                        stale_after_hours=stale_after_hours,
                        feed_health=feed_health,
                        group_by_fleet=group_by_fleet,
                        show_offline_banner=show_offline_banner,
                    ),
                ),
            )
        )
    if generated_at.tzinfo is None:
        raise ValueError("Report time must be timezone-aware")

    briefing = build_fleet_briefing(
        fleet, positions, generated_at, stale_after_hours, feed_health
    )
    small_width = min(
        FONT_B_PRINTABLE_WIDTH,
        max(width, round(width * 4 / 3)),
    )
    column_width = (small_width - COLUMN_GAP) // 2
    segments: list[ReceiptSegment] = []

    header = []
    if show_offline_banner and is_feed_offline(positions, generated_at):
        header.extend([OFFLINE_BANNER, ""])
    header.extend(
        [
            "FLEET OPERATIONS BRIEF",
            _report_timestamp(generated_at),
            *briefing.summary,
            f"AIS Source: {briefing.source}",
            "=" * width,
        ]
    )
    segments.append(ReceiptSegment(FONT_A, _lines(header)))

    line_by_vessel = {
        vessel.name.upper(): vessel.cruise_line
        for vessel in fleet.vessels
        if vessel.active
    }
    for heading, vessels in _available_sections(
        fleet, briefing, line_by_vessel, group_by_fleet
    ):
        segments.append(
            ReceiptSegment(FONT_A, _lines(["", heading, "-" * width]))
        )
        segments.extend(
            _format_pairs(
                [
                    _ship_slots(
                        vessel,
                        positions[vessel.name.casefold()],
                        column_width,
                    )
                    for vessel in vessels
                ],
                column_width,
            )
        )

    if briefing.missing_names:
        segments.append(
            ReceiptSegment(
                FONT_A,
                _lines(
                    [
                        "",
                        f"NO RECENT AIS ({len(briefing.missing_names)})",
                        "-" * width,
                    ]
                ),
            )
        )
        segments.extend(
            _format_pairs(
                [
                    _missing_slots(name, column_width)
                    for name in briefing.missing_names
                ],
                column_width,
            )
        )
    segments.append(
        ReceiptSegment(
            FONT_A,
            _lines(
                [
                    "",
                    "Latest available AIS positions",
                    "Times are estimated",
                ]
            ),
        )
    )
    receipt = PrinterReceipt(tuple(segments))
    _validate_ascii(receipt.text)
    return receipt


def render_cached_printer_report(
    cache: Optional[PositionCache] = None,
    generated_at: Optional[datetime] = None,
    width: Optional[int] = None,
    fleet_profile: str = "main",
    show_offline_banner: bool = False,
) -> PrinterReceipt:
    active_cache = cache or PositionCache()
    settings = load_settings()
    report_time = generated_at or datetime.now(timezone.utc)
    return format_printer_receipt(
        load_fleet(profile=fleet_profile),
        active_cache.load(),
        report_time,
        width=width or int(settings["receipt_width"]),
        stale_after_hours=float(settings["stale_after_hours"]),
        feed_health=active_cache.health(),
        group_by_fleet=fleet_profile.casefold() == "all",
        two_column=bool(settings.get("TWO_COLUMN_PRINT", False)),
        show_offline_banner=show_offline_banner,
    )


def _available_sections(
    fleet: FleetData,
    briefing: FleetBriefing,
    line_by_vessel: Mapping[str, str],
    grouped: bool,
) -> list[tuple[str, list[VesselBrief]]]:
    if grouped:
        categories = (
            ("HOLLAND AMERICA LINE", {"Holland America Line"}),
            ("SEABOURN", {"Seabourn"}),
            ("CARNIVAL CORPORATION", CARNIVAL_CORPORATION_LINES),
            (
                "OTHER CRUISE LINES",
                set(fleet.cruise_line_order)
                - {"Holland America Line", "Seabourn"}
                - CARNIVAL_CORPORATION_LINES,
            ),
        )
    else:
        categories = tuple(
            (line.upper(), {line}) for line in fleet.cruise_line_order
        )
    sections = []
    for heading, lines in categories:
        members = [
            vessel
            for vessel in briefing.vessels
            if line_by_vessel.get(vessel.name) in lines
        ]
        if members:
            sections.append((heading, members))
    return sections


def _ship_slots(
    vessel: VesselBrief,
    position: Position,
    width: int,
) -> list[list[str]]:
    status, speed, course = _movement_rows(position, width)
    destination, eta = _voyage_lines(vessel.voyage, width)
    stationary_status = _stationary_status_label(position)
    if stationary_status and not destination and not eta:
        status = stationary_status
        speed = "-" * width
        course = " "
    age_label = f"AIS {_compact_age(vessel.age)}"
    location_fields = [_receipt_location(vessel.location)]
    if vessel.landmark:
        location_fields.append(_receipt_location(vessel.landmark))
    location_lines = [
        line
        for field in location_fields
        for line in _wrap_ascii(field, width)
    ]
    coordinates = _coordinates(vessel.coordinates)
    if len(coordinates) > width:
        raise ValueError("Compact coordinates exceed printer column width")
    return [
        _wrap_ascii(vessel.name, width),
        location_lines,
        [coordinates],
        [status],
        [speed],
        [course],
        _wrap_ascii(destination, width) if destination else [""],
        _wrap_ascii(eta, width) if eta else [""],
        _wrap_ascii(f"UTC {vessel.utc_time}", width),
        _wrap_ascii(
            f"LOCAL {vessel.local_time.replace('Same as Seattle', 'Seattle')}",
            width,
        ),
        _wrap_ascii(age_label, width),
    ]


def _missing_slots(name: str, width: int) -> list[list[str]]:
    return [
        _wrap_ascii(name, width),
        ["[No AIS]"],
    ]


def _movement_rows(
    position: Position,
    width: int,
) -> tuple[str, str, str]:
    status = navigational_status(position.navigational_status)
    underway = is_underway_status(position.navigational_status)
    normalized = " ".join(status.upper().split())
    if underway:
        visible_status = "UNDERWAY"
    elif _stationary_status_label(position):
        visible_status = _stationary_status_label(position) or ""
    elif normalized in {
        "NAVIGATIONAL STATUS UNAVAILABLE",
        "UNDEFINED / DEFAULT",
        "UNKNOWN",
    }:
        visible_status = "UNKNOWN"
    else:
        visible_status = _fit_one_line(normalized, width)

    speed = ""
    course = ""
    if underway:
        if _valid_number(position.speed_knots) and position.speed_knots >= 0:
            speed = f"{position.speed_knots:.1f} kn"
        if (
            _valid_number(position.course_degrees)
            and 0 <= position.course_degrees < 360
        ):
            degrees = round(position.course_degrees) % 360
            course = f"{degrees:03d} deg {_course_direction(degrees)}"

    # A single space forces the paired renderer to retain the reserved row
    # even when neither ship has a value for it.
    return visible_status, speed or " ", course or " "


def _stationary_status_label(position: Position) -> Optional[str]:
    normalized = " ".join(
        navigational_status(position.navigational_status).upper().split()
    )
    if normalized in {"AT ANCHOR", "ANCHORED"}:
        return "ANCHORED"
    if normalized in {"MOORED", "ALONGSIDE"}:
        return "MOORED"
    return None


def _fit_one_line(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    shortened = textwrap.shorten(value, width=width, placeholder="...")
    return shortened if shortened != "..." else value[: width - 3] + "..."


def _course_direction(degrees: int) -> str:
    directions = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
    return directions[int((degrees + 22.5) // 45) % len(directions)]


def _valid_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
    )


def _voyage_lines(value: Optional[str], width: int) -> tuple[str, str]:
    if not value:
        return "", ""
    lines = [_ascii(line) for line in value.splitlines() if line.strip()]
    if not lines:
        return "", ""
    destination = lines[0]
    if destination.startswith("Destination "):
        destination = destination.removeprefix("Destination ")
    elif ">" in destination:
        destination = destination.rsplit(">", 1)[-1].strip()
    destination = destination.split(",", 1)[0].strip()
    destination = " ".join(destination.split())
    destination = textwrap.shorten(
        destination,
        width=max(4, width - len("DEST ")),
        placeholder="...",
    )
    destination = f"DEST {destination}" if destination else ""
    return destination, lines[1] if len(lines) > 1 else ""


def _coordinates(value: str) -> str:
    cleaned = _ascii(value).replace("'", "")
    cleaned = re.sub(r"(\d)\s+([NSEW])\b", r"\1\2", cleaned)
    match = re.match(
        r"^(\d+\s+\d+(?:\.\d+)?[NS])\s+"
        r"(\d+\s+\d+(?:\.\d+)?[EW])$",
        cleaned,
    )
    return f"{match.group(1)} | {match.group(2)}" if match else cleaned


def _format_pairs(
    blocks: Sequence[list[list[str]]], width: int
) -> list[ReceiptSegment]:
    output: list[ReceiptSegment] = []
    for index in range(0, len(blocks), 2):
        left = blocks[index]
        right = blocks[index + 1] if index + 1 < len(blocks) else []
        if not right:
            _append_unpaired_block(output, left, width)
            _append_segment(output, ReceiptSegment(FONT_B, "\n"))
            continue

        slot_count = max(len(left), len(right))
        for slot_index in range(slot_count):
            left_lines = _column_slot_lines(
                left[slot_index] if slot_index < len(left) else [""],
                width,
            )
            right_lines = _column_slot_lines(
                right[slot_index] if slot_index < len(right) else [""],
                width,
            )
            # Every semantic slot reserves at least one physical line, even
            # when both optional values are blank.
            line_count = max(1, len(left_lines), len(right_lines))
            for line_index in range(line_count):
                left_line = (
                    left_lines[line_index] if line_index < len(left_lines) else ""
                )
                right_line = (
                    right_lines[line_index] if line_index < len(right_lines) else ""
                )
                _append_segment(
                    output,
                    ReceiptSegment(
                        FONT_B,
                        _fixed_paired_line(left_line, right_line, width),
                        emphasized=slot_index == 0,
                    ),
                )
        _append_segment(output, ReceiptSegment(FONT_B, "\n"))
    return output


def _column_slot_lines(lines: Sequence[str], width: int) -> list[str]:
    fixed: list[str] = []
    for line in lines or ("",):
        fixed.extend(_wrap_ascii(line, width) if line.strip() else [""])
    return fixed or [""]


def _fixed_paired_line(left: str, right: str, width: int) -> str:
    left_line = _fit_one_line(_ascii(left), width)
    right_line = _fit_one_line(_ascii(right), width)
    line = left_line.ljust(width) + (" " * COLUMN_GAP) + right_line.ljust(width)
    if len(line) > FONT_B_PRINTABLE_WIDTH:
        raise ValueError("Combined ship row exceeded the printer-safe width")
    return line + "\n"


def _append_unpaired_block(
    output: list[ReceiptSegment],
    block: list[list[str]],
    width: int,
) -> None:
    """Retain the established final single-ship layout unchanged."""
    for slot_index, slot_lines in enumerate(block):
        if not any(slot_lines):
            continue
        for line in slot_lines:
            if len(line) > width:
                raise ValueError("Ship field exceeded its fixed printer column")
            existing_line = (
                line.ljust(width) + (" " * COLUMN_GAP) + "".ljust(width)
            )
            _append_segment(
                output,
                ReceiptSegment(
                    FONT_B,
                    _ascii(existing_line, strip=False).rstrip() + "\n",
                    emphasized=slot_index == 0,
                ),
            )


def _append_segment(
    segments: list[ReceiptSegment], segment: ReceiptSegment
) -> None:
    if (
        segments
        and segments[-1].font == segment.font
        and segments[-1].emphasized == segment.emphasized
    ):
        previous = segments[-1]
        segments[-1] = ReceiptSegment(
            previous.font,
            previous.text + segment.text,
            previous.emphasized,
        )
    else:
        segments.append(segment)


def _compact_age(value: str) -> str:
    cleaned = _ascii(value)
    replacements = (
        (r"\bminutes?\b", "min"),
        (r"\bhours?\b", "hr"),
        (r"\bdays?\b", lambda match: "day" if match.group(0) == "day" else "days"),
    )
    for pattern, replacement in replacements:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
    return cleaned


def _receipt_location(value: str) -> str:
    """Return printer-safe location text with an indivisible rounded nm token."""
    cleaned = _ascii(value)
    if cleaned.casefold() == "same as seattle":
        return "Seattle"

    state_names = "|".join(
        re.escape(name)
        for name in sorted(
            US_STATE_ABBREVIATIONS,
            key=len,
            reverse=True,
        )
    )

    def abbreviated_state(match: re.Match[str]) -> str:
        return (
            match.group("prefix")
            + US_STATE_ABBREVIATIONS[match.group("state")]
        )

    cleaned = re.sub(
        rf"(?P<prefix>,\s+|\bof\s+)"
        rf"(?P<state>{state_names})\b",
        abbreviated_state,
        cleaned,
    )

    def rounded_distance(match: re.Match[str]) -> str:
        nautical_miles = Decimal(match.group(1)).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
        return f"{nautical_miles}nm"

    return re.sub(
        r"\b(\d+(?:\.\d+)?)\s*nm\b",
        rounded_distance,
        cleaned,
        flags=re.IGNORECASE,
    )


def _wrap_ascii(value: str, width: int) -> list[str]:
    return textwrap.wrap(
        _ascii(value),
        width=width,
        break_long_words=True,
        break_on_hyphens=True,
    ) or [""]


def _ascii(value: str, *, strip: bool = True) -> str:
    replacements = {
        "â†’": ">",
        "→": ">",
        "Â°": " ",
        "°": " ",
        "â€¢": "*",
        "•": "*",
        "â”€": "-",
        "─": "-",
        "â•": "=",
        "═": "=",
        "–": "-",
        "—": "-",
        "’": "'",
        "“": '"',
        "”": '"',
    }
    cleaned = str(value)
    for source, replacement in replacements.items():
        cleaned = cleaned.replace(source, replacement)
    cleaned = unicodedata.normalize("NFKD", cleaned)
    result = cleaned.encode("ascii", errors="ignore").decode("ascii")
    return result.strip() if strip else result


def _lines(lines: Iterable[str]) -> str:
    return "\n".join(_ascii(line, strip=False).rstrip() for line in lines) + "\n"


def _report_timestamp(value: datetime) -> str:
    from zoneinfo import ZoneInfo

    seattle = value.astimezone(ZoneInfo("America/Los_Angeles"))
    return f"{seattle:%Y-%m-%d %H:%M} Seattle"


def _validate_ascii(value: str) -> None:
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("Printer receipt contains unsupported Unicode") from exc

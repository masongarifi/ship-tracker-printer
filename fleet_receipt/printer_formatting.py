import re
import textwrap
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, Mapping, Optional, Sequence

from .briefing import FleetBriefing, VesselBrief, build_fleet_briefing
from .cache import PositionCache
from .config import load_fleet, load_settings
from .formatting import format_receipt
from .models import FleetData, Position

FONT_A = "a"
FONT_B = "b"
COLUMN_GAP = 2
CARNIVAL_CORPORATION_LINES = {
    "Carnival Cruise Line",
    "Princess Cruises",
    "Cunard",
    "P&O Cruises",
    "Costa Cruises",
    "AIDA Cruises",
}


@dataclass(frozen=True)
class ReceiptSegment:
    font: str
    text: str


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
                    ),
                ),
            )
        )
    if generated_at.tzinfo is None:
        raise ValueError("Report time must be timezone-aware")

    briefing = build_fleet_briefing(
        fleet, positions, generated_at, stale_after_hours, feed_health
    )
    small_width = max(width, round(width * 4 / 3))
    column_width = (small_width - COLUMN_GAP) // 2
    segments: list[ReceiptSegment] = []

    header = [
        "FLEET OPERATIONS BRIEF",
        _report_timestamp(generated_at),
        *briefing.summary,
        f"AIS Source: {briefing.source}",
        "=" * width,
    ]
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
        segments.append(
            ReceiptSegment(
                FONT_B,
                _format_pairs(
                    [_ship_slots(vessel, column_width) for vessel in vessels],
                    column_width,
                ),
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
        segments.append(
            ReceiptSegment(
                FONT_B,
                _format_pairs(
                    [
                        _missing_slots(name, column_width)
                        for name in briefing.missing_names
                    ],
                    column_width,
                ),
            )
        )
        segments.append(
            ReceiptSegment(
                FONT_A,
                _lines(_wrap_ascii(f"! {briefing.missing_reason}", width)),
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


def _ship_slots(vessel: VesselBrief, width: int) -> list[list[str]]:
    movement, speed = _movement_lines(vessel.movement)
    destination, eta = _voyage_lines(vessel.voyage)
    age_marker = "!" if vessel.age_heading.casefold().startswith("last") else "*"
    age_label = (
        f"{age_marker} {vessel.age_heading} {vessel.age}"
    )
    location = [f"@ {vessel.location}"]
    if vessel.landmark:
        location.append(f"@ {vessel.landmark}")
    return [
        _wrap_ascii(vessel.name, width),
        _wrap_ascii(" | ".join(location), width),
        _wrap_ascii(_coordinates(vessel.coordinates), width),
        _wrap_ascii(movement, width),
        _wrap_ascii(speed, width) if speed else [""],
        _wrap_ascii(destination, width) if destination else [""],
        _wrap_ascii(eta, width) if eta else [""],
        _wrap_ascii(f"UTC {vessel.utc_time}", width),
        _wrap_ascii(f"LOCAL {vessel.local_time}", width),
        _wrap_ascii(age_label, width),
    ]


def _missing_slots(name: str, width: int) -> list[list[str]]:
    return [
        _wrap_ascii(name, width),
        ["[NO AIS]"],
        ["! No cached position"],
    ]


def _movement_lines(value: str) -> tuple[str, str]:
    cleaned = _ascii(value)
    match = re.match(
        r"^(.*?)\s+CRS\s+(\d{1,3})\s+at\s+([0-9.]+)\s+kts?$",
        cleaned,
        re.IGNORECASE,
    )
    if match:
        return (
            f"{match.group(1).upper()} | CRS {int(match.group(2)):03d}",
            f"{match.group(3)} kt",
        )
    speed_match = re.match(
        r"^(.*?)\s+at\s+([0-9.]+)\s+kts?$", cleaned, re.IGNORECASE
    )
    if speed_match:
        return speed_match.group(1).upper(), f"{speed_match.group(2)} kt"
    return cleaned.upper(), ""


def _voyage_lines(value: Optional[str]) -> tuple[str, str]:
    if not value:
        return "", ""
    lines = [_ascii(line) for line in value.splitlines() if line.strip()]
    if not lines:
        return "", ""
    destination = lines[0]
    if destination.startswith("Destination "):
        destination = f"> {destination.removeprefix('Destination ')}"
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


def _format_pairs(blocks: Sequence[list[list[str]]], width: int) -> str:
    output: list[str] = []
    for index in range(0, len(blocks), 2):
        left = blocks[index]
        right = blocks[index + 1] if index + 1 < len(blocks) else []
        slot_count = max(len(left), len(right))
        for slot_index in range(slot_count):
            left_lines = left[slot_index] if slot_index < len(left) else [""]
            right_lines = right[slot_index] if slot_index < len(right) else [""]
            if not any(left_lines) and not any(right_lines):
                continue
            line_count = max(len(left_lines), len(right_lines))
            for line_index in range(line_count):
                left_line = (
                    left_lines[line_index] if line_index < len(left_lines) else ""
                )
                right_line = (
                    right_lines[line_index] if line_index < len(right_lines) else ""
                )
                output.append(
                    left_line.ljust(width)
                    + (" " * COLUMN_GAP)
                    + right_line.ljust(width)
                )
        output.append("")
    return _lines(output)


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

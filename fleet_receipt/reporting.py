from datetime import datetime, timezone
from typing import Optional

from .cache import PositionCache
from .config import load_fleet, load_settings
from .formatting import format_receipt


def render_cached_report(
    cache: Optional[PositionCache] = None,
    generated_at: Optional[datetime] = None,
    width: Optional[int] = None,
    fleet_profile: str = "main",
) -> str:
    """Render the canonical cached fleet report for CLI, web, and printing."""
    active_cache = cache or PositionCache()
    settings = load_settings()
    report_time = generated_at or datetime.now(timezone.utc)
    return format_receipt(
        load_fleet(profile=fleet_profile),
        active_cache.load(),
        report_time,
        width=width or int(settings["receipt_width"]),
        stale_after_hours=float(settings["stale_after_hours"]),
        feed_health=active_cache.health(),
        group_by_fleet=fleet_profile.casefold() == "all",
    )

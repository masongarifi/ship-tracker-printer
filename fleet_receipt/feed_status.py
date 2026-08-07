from datetime import datetime, timezone
from typing import Dict, Optional

from .models import Position

FEED_OFFLINE_AFTER_SECONDS = 2 * 60 * 60


def newest_position_timestamp(
    positions: Dict[str, Position]
) -> Optional[datetime]:
    return max(
        (position.position_timestamp for position in positions.values()),
        default=None,
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def is_feed_offline(positions: Dict[str, Position], now: datetime) -> bool:
    newest = newest_position_timestamp(positions)
    if newest is None:
        return True
    age_seconds = (_aware_utc(now) - _aware_utc(newest)).total_seconds()
    return age_seconds >= FEED_OFFLINE_AFTER_SECONDS

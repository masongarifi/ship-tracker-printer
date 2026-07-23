from typing import Dict, Sequence

from ..models import Position, Vessel
from .base import PositionProvider


class MarineTrafficNotConfigured(RuntimeError):
    pass


class MarineTrafficProvider(PositionProvider):
    """Deliberate stub; no endpoint or response contract is assumed."""

    def fetch_positions(self, vessels: Sequence[Vessel]) -> Dict[str, Position]:
        raise MarineTrafficNotConfigured(
            "MarineTraffic integration requires official API documentation, plan details, "
            "credentials, and a redacted sample response"
        )


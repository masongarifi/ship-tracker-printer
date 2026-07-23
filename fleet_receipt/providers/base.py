from abc import ABC, abstractmethod
from typing import Dict, Sequence

from ..models import Position, Vessel


class PositionProvider(ABC):
    @abstractmethod
    def fetch_positions(self, vessels: Sequence[Vessel]) -> Dict[str, Position]:
        """Fetch at most one newest position per vessel, keyed by casefolded name."""


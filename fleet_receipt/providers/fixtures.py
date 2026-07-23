import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Sequence

from ..ais_status import navigational_status
from ..config import PROJECT_ROOT
from ..models import Position, Vessel
from .base import PositionProvider


class FixturePositionProvider(PositionProvider):
    def __init__(self, path: Path = PROJECT_ROOT / "fixtures" / "vessel_positions.json"):
        self.path = path

    def fetch_positions(self, vessels: Sequence[Vessel]) -> Dict[str, Position]:
        records = json.loads(self.path.read_text(encoding="utf-8"))["positions"]
        configured = {v.name.casefold() for v in vessels}
        result: Dict[str, Position] = {}
        for row in records:
            key = row["vessel_name"].casefold()
            if key not in configured:
                continue
            result[key] = Position(
                vessel_name=row["vessel_name"],
                latitude=float(row["latitude"]),
                longitude=float(row["longitude"]),
                speed_knots=_optional_float(row.get("speed_knots")),
                course_degrees=_optional_float(row.get("course_degrees")),
                navigational_status=navigational_status(row["navigational_status"]),
                destination=row.get("destination"),
                reported_eta=row.get("reported_eta"),
                position_timestamp=_datetime(row["position_timestamp"]),
                source=row.get("source", "Fixture AIS data"),
                position_type=row.get("position_type"),
                broad_location=row.get("broad_location"),
                broad_timezone=row.get("broad_timezone"),
            )
        return result


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _optional_float(value):
    return None if value is None else float(value)

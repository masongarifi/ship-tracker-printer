import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .config import PROJECT_ROOT
from .models import Position

DEFAULT_CACHE_PATH = PROJECT_ROOT / "work" / "position-cache.json"


class PositionCache:
    def __init__(self, path: Path = DEFAULT_CACHE_PATH):
        self.path = path

    def load(self) -> Dict[str, Position]:
        data = self._read()
        return {
            key: _position_from_dict(value)
            for key, value in data.get("positions", {}).items()
        }

    def update(self, position: Position) -> None:
        payload = self._read()
        payload.setdefault("positions", {})[
            position.vessel_name.casefold()
        ] = _position_to_dict(position)
        payload["updated_at"] = datetime.now().astimezone().isoformat()
        self._write(payload)

    def update_health(self, status: str, error: Optional[str] = None) -> None:
        payload = self._read()
        payload["health"] = {
            "source": "Terrestrial",
            "status": status,
            "error": error,
            "checked_at": datetime.now().astimezone().isoformat(),
        }
        self._write(payload)

    def health(self) -> Dict[str, Any]:
        return dict(self._read().get("health", {"source": "Terrestrial", "status": "unknown"}))

    def _read(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, payload: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)


def _position_to_dict(position: Position):
    return {
        "vessel_name": position.vessel_name,
        "latitude": position.latitude,
        "longitude": position.longitude,
        "speed_knots": position.speed_knots,
        "course_degrees": position.course_degrees,
        "navigational_status": position.navigational_status,
        "destination": position.destination,
        "reported_eta": position.reported_eta,
        "position_timestamp": position.position_timestamp.isoformat(),
        "source": position.source,
        "position_type": position.position_type,
        "broad_location": position.broad_location,
        "broad_timezone": position.broad_timezone,
    }


def _position_from_dict(row) -> Position:
    return Position(
        vessel_name=row["vessel_name"],
        latitude=float(row["latitude"]),
        longitude=float(row["longitude"]),
        speed_knots=row.get("speed_knots"),
        course_degrees=row.get("course_degrees"),
        navigational_status=row["navigational_status"],
        destination=row.get("destination"),
        reported_eta=row.get("reported_eta"),
        position_timestamp=datetime.fromisoformat(row["position_timestamp"]),
        source=row.get("source", "AISstream.io cache"),
        position_type=row.get("position_type"),
        broad_location=row.get("broad_location"),
        broad_timezone=row.get("broad_timezone"),
    )

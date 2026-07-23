import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from .ais_status import is_underway_status
from .config import PROJECT_ROOT
from .models import Position

APPLICATION_NAME = "ship-tracker-printer"
DATABASE_NAME = "ais-cache.sqlite3"
LEGACY_CACHE_PATH = PROJECT_ROOT / "work" / "position-cache.json"


def application_data_directory() -> Path:
    override = os.environ.get("SHIP_TRACKER_DATA_DIR")
    if override:
        return Path(override).expanduser()

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home).expanduser() / APPLICATION_NAME

    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / APPLICATION_NAME

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APPLICATION_NAME

    return Path.home() / ".local" / "share" / APPLICATION_NAME


def default_cache_path() -> Path:
    return application_data_directory() / DATABASE_NAME


class PositionCache:
    """Crash-safe persistent storage with one independently updated row per vessel."""

    def __init__(
        self,
        path: Optional[Path] = None,
        legacy_path: Optional[Path] = None,
    ):
        self.path = Path(path) if path is not None else default_cache_path()
        self.legacy_path = (
            Path(legacy_path)
            if legacy_path is not None
            else (LEGACY_CACHE_PATH if path is None else None)
        )
        database_existed = self.path.exists()
        self._initialize()
        if not database_existed:
            self._migrate_legacy_json()

    def load(self) -> Dict[str, Position]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT vessel_key, payload FROM positions ORDER BY vessel_key"
            ).fetchall()
        return {
            row["vessel_key"]: _position_from_dict(json.loads(row["payload"]))
            for row in rows
        }

    def update(self, position: Position) -> None:
        vessel_key = position.vessel_name.casefold()
        now = datetime.now().astimezone().isoformat()
        with self._connect() as connection:
            previous_row = connection.execute(
                "SELECT payload FROM positions WHERE vessel_key = ?",
                (vessel_key,),
            ).fetchone()
            previous = (
                _position_from_dict(json.loads(previous_row["payload"]))
                if previous_row is not None
                else None
            )
            position = _with_underway_since(position, previous)
            payload = json.dumps(
                _position_to_dict(position),
                separators=(",", ":"),
                ensure_ascii=False,
            )
            connection.execute(
                """
                INSERT INTO positions (vessel_key, payload, cached_at)
                VALUES (?, ?, ?)
                ON CONFLICT(vessel_key) DO UPDATE SET
                    payload = excluded.payload,
                    cached_at = excluded.cached_at
                """,
                (vessel_key, payload, now),
            )

    def update_health(self, status: str, error: Optional[str] = None) -> None:
        health = {
            "source": "Terrestrial",
            "status": status,
            "error": error,
            "checked_at": datetime.now().astimezone().isoformat(),
        }
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO metadata (key, value)
                VALUES ('health', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (json.dumps(health, separators=(",", ":")),),
            )

    def health(self) -> Dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'health'"
            ).fetchone()
        if row is None:
            return {"source": "Terrestrial", "status": "unknown"}
        return dict(json.loads(row["value"]))

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            self.path.parent.chmod(0o700)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS positions (
                    vessel_key TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    cached_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                PRAGMA user_version = 1;
                """
            )
        if os.name != "nt":
            self.path.chmod(0o600)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _migrate_legacy_json(self) -> None:
        if self.legacy_path is None or not self.legacy_path.exists():
            return
        try:
            legacy = json.loads(self.legacy_path.read_text(encoding="utf-8"))
            positions = legacy.get("positions", {})
            health = legacy.get("health")
        except (OSError, json.JSONDecodeError, AttributeError):
            return

        now = datetime.now().astimezone().isoformat()
        with self._connect() as connection:
            for vessel_key, row in positions.items():
                position = _position_from_dict(row)
                payload = json.dumps(
                    _position_to_dict(position),
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO positions (vessel_key, payload, cached_at)
                    VALUES (?, ?, ?)
                    """,
                    (vessel_key.casefold(), payload, now),
                )
            if isinstance(health, dict):
                connection.execute(
                    "INSERT OR IGNORE INTO metadata (key, value) VALUES ('health', ?)",
                    (json.dumps(health, separators=(",", ":")),),
                )
            connection.execute(
                """
                INSERT OR REPLACE INTO metadata (key, value)
                VALUES ('legacy_json_migrated_at', ?)
                """,
                (now,),
            )


def _position_to_dict(position: Position) -> Dict[str, Any]:
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
        "underway_since": (
            position.underway_since.isoformat()
            if isinstance(position.underway_since, datetime)
            else None
        ),
    }


def _position_from_dict(row: Dict[str, Any]) -> Position:
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
        underway_since=_optional_datetime(row.get("underway_since")),
    )


def _with_underway_since(
    position: Position, previous: Optional[Position]
) -> Position:
    if not is_underway_status(position.navigational_status):
        return replace(position, underway_since=None)
    if previous is None or not is_underway_status(previous.navigational_status):
        return replace(position, underway_since=position.position_timestamp)
    return replace(position, underway_since=previous.underway_since)


def _optional_datetime(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None

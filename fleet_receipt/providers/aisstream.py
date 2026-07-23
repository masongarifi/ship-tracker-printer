import asyncio
import json
import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence

from ..ais_status import navigational_status
from ..config import PROJECT_ROOT
from ..models import Position, Vessel
from .base import PositionProvider

AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"
WORLD_BOUNDING_BOX = [[[-90.0, -180.0], [90.0, 180.0]]]


class AISStreamError(RuntimeError):
    pass


class AISStreamProvider(PositionProvider):
    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout_seconds: float = 60.0,
        env_path: Path = PROJECT_ROOT / ".env",
    ):
        self.api_key = api_key or _load_api_key(env_path)
        self.timeout_seconds = timeout_seconds

    def fetch_positions(self, vessels: Sequence[Vessel]) -> Dict[str, Position]:
        configured = [vessel for vessel in vessels if vessel.active and vessel.mmsi]
        if not configured:
            raise AISStreamError("No active vessels have an MMSI configured")
        if len(configured) > 50:
            raise AISStreamError("AISstream.io supports at most 50 MMSIs per subscription")
        try:
            return asyncio.run(self._fetch(configured))
        except AISStreamError:
            raise
        except Exception as exc:
            raise AISStreamError(f"AISstream.io connection failed: {exc}") from exc

    def listen_forever(
        self,
        vessels: Sequence[Vessel],
        on_position: Callable[[Position], None],
        on_health: Optional[Callable[[str, Optional[str]], None]] = None,
        initial_positions: Optional[Dict[str, Position]] = None,
    ) -> None:
        configured = [vessel for vessel in vessels if vessel.active and vessel.mmsi]
        if not configured:
            raise AISStreamError("No active vessels have an MMSI configured")
        if len(configured) > 50:
            raise AISStreamError("AISstream.io supports at most 50 MMSIs per subscription")
        asyncio.run(
            self._listen_forever(
                configured, on_position, on_health, initial_positions or {}
            )
        )

    async def _listen_forever(
        self,
        vessels: Sequence[Vessel],
        on_position: Callable[[Position], None],
        on_health: Optional[Callable[[str, Optional[str]], None]],
        initial_positions: Dict[str, Position],
    ) -> None:
        try:
            import websockets
        except ImportError as exc:
            raise AISStreamError(
                "The websockets package is required; run: python -m pip install -e ."
            ) from exc

        by_mmsi = {str(vessel.mmsi): vessel for vessel in vessels}
        subscription = json.dumps(build_subscription(self.api_key, list(by_mmsi)))
        static_data: Dict[str, Dict[str, Optional[str]]] = {}
        latest_positions: Dict[str, Position] = {
            mmsi: initial_positions[vessel.name.casefold()]
            for mmsi, vessel in by_mmsi.items()
            if vessel.name.casefold() in initial_positions
        }
        delay = 1
        while True:
            try:
                if on_health:
                    on_health("connecting", None)
                async with websockets.connect(AISSTREAM_URL, open_timeout=10) as websocket:
                    await websocket.send(subscription)
                    if on_health:
                        on_health("connected", None)
                    delay = 1
                    async for payload in websocket:
                        message = json.loads(payload)
                        if "error" in message:
                            raise AISStreamError(str(message["error"]))
                        static = static_data_from_message(message)
                        if static is not None:
                            mmsi, details = static
                            static_data[mmsi] = details
                            existing = latest_positions.get(mmsi)
                            if existing is not None:
                                enriched = _enrich_position(existing, details)
                                latest_positions[mmsi] = enriched
                                on_position(enriched)
                            continue
                        position = position_from_message(message, by_mmsi)
                        if position is not None:
                            mmsi = str(
                                message["Message"]["PositionReport"].get("UserID", "")
                            )
                            position = _enrich_position(position, static_data.get(mmsi, {}))
                            latest_positions[mmsi] = position
                            on_position(position)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if on_health:
                    on_health("error", str(exc))
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)

    async def _fetch(self, vessels: Sequence[Vessel]) -> Dict[str, Position]:
        try:
            import websockets
        except ImportError as exc:
            raise AISStreamError(
                "The websockets package is required; run: python -m pip install -e ."
            ) from exc

        by_mmsi = {str(vessel.mmsi): vessel for vessel in vessels}
        subscription = build_subscription(self.api_key, list(by_mmsi))
        positions: Dict[str, Position] = {}
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout_seconds

        async with websockets.connect(AISSTREAM_URL, open_timeout=10) as websocket:
            await websocket.send(json.dumps(subscription))
            while len(positions) < len(by_mmsi):
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                try:
                    payload = await asyncio.wait_for(websocket.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    break
                message = json.loads(payload)
                position = position_from_message(message, by_mmsi)
                if position is not None:
                    positions[position.vessel_name.casefold()] = position
        return positions


def build_subscription(api_key: str, mmsis: Sequence[str]) -> Dict[str, Any]:
    if not api_key or not api_key.strip():
        raise AISStreamError("AISSTREAM_API_KEY is missing or empty")
    return {
        "APIKey": api_key.strip(),
        "BoundingBoxes": WORLD_BOUNDING_BOX,
        "FiltersShipMMSI": [str(mmsi) for mmsi in mmsis],
        "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
    }


def position_from_message(
    message: Dict[str, Any], vessels_by_mmsi: Dict[str, Vessel]
) -> Optional[Position]:
    if message.get("MessageType") != "PositionReport":
        return None
    body = message.get("Message", {}).get("PositionReport", {})
    metadata = message.get("MetaData") or message.get("Metadata") or {}
    mmsi = str(body.get("UserID") or metadata.get("MMSI") or "")
    vessel = vessels_by_mmsi.get(mmsi)
    if vessel is None or not body.get("Valid", True):
        return None
    try:
        latitude = float(body["Latitude"])
        longitude = float(body["Longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return Position(
        vessel_name=vessel.name,
        latitude=latitude,
        longitude=longitude,
        speed_knots=_optional_float(body.get("Sog")),
        course_degrees=_optional_float(body.get("Cog")),
        navigational_status=navigational_status(body.get("NavigationalStatus")),
        destination=None,
        reported_eta=None,
        position_timestamp=_message_time(metadata.get("time_utc")),
        source="AISstream.io",
    )


def static_data_from_message(
    message: Dict[str, Any],
) -> Optional[tuple[str, Dict[str, Optional[str]]]]:
    if message.get("MessageType") != "ShipStaticData":
        return None
    body = message.get("Message", {}).get("ShipStaticData", {})
    if not body.get("Valid", True):
        return None
    mmsi = str(body.get("UserID") or "")
    if not mmsi:
        return None
    destination = str(body.get("Destination") or "").strip(" @") or None
    return mmsi, {
        "destination": destination,
        "reported_eta": _static_eta(body.get("Eta"), message.get("MetaData", {})),
    }


def _enrich_position(
    position: Position, details: Dict[str, Optional[str]]
) -> Position:
    return replace(
        position,
        destination=details.get("destination") or position.destination,
        reported_eta=details.get("reported_eta") or position.reported_eta,
    )


def _static_eta(value: Any, metadata: Dict[str, Any]) -> Optional[str]:
    if not isinstance(value, dict):
        return None
    try:
        month = int(value.get("Month", 0))
        day = int(value.get("Day", 0))
        hour = int(value.get("Hour", 24))
        minute = int(value.get("Minute", 60))
        if not (1 <= month <= 12 and 1 <= day <= 31 and 0 <= hour <= 23 and 0 <= minute <= 59):
            return None
    except (TypeError, ValueError):
        return None
    received = _message_time(metadata.get("time_utc"))
    year = received.year
    candidate = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    if candidate < received.replace(day=1) - timedelta(days=31):
        candidate = candidate.replace(year=year + 1)
    return candidate.isoformat()


def _load_api_key(path: Path) -> str:
    value = os.environ.get("AISSTREAM_API_KEY")
    if value:
        return value.strip()
    if path.exists():
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, candidate = line.split("=", 1)
            if name.strip() == "AISSTREAM_API_KEY":
                return candidate.strip().strip("\"'")
    raise AISStreamError(
        f"AISSTREAM_API_KEY is not set; add it to the environment or {path}"
    )


def _message_time(value: Any) -> datetime:
    if isinstance(value, str):
        for pattern in ("%Y-%m-%d %H:%M:%S.%f %z UTC", "%Y-%m-%d %H:%M:%S %z UTC"):
            try:
                return datetime.strptime(value, pattern)
            except ValueError:
                pass
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _optional_float(value: Any) -> Optional[float]:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None

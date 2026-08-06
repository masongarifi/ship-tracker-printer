import asyncio
import json
import logging
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
MAX_MMSIS_PER_SUBSCRIPTION = 50
SUBSCRIPTION_ROTATION_SECONDS = 30.0
NO_FRAME_WARNING_SECONDS = 30.0
RAW_FRAME_LOG_LIMIT = 2000
POSITION_MESSAGE_TYPES = (
    "PositionReport",
    "StandardClassBPositionReport",
)
SUBSCRIPTION_MESSAGE_TYPES = (*POSITION_MESSAGE_TYPES, "ShipStaticData")
LOGGER = logging.getLogger(__name__)


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
        configured = list(_configured_by_mmsi(vessels).values())
        if not configured:
            raise AISStreamError("No active vessels have an MMSI configured")
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
        configured = list(_configured_by_mmsi(vessels).values())
        if not configured:
            raise AISStreamError("No active vessels have an MMSI configured")
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
        all_mmsis = list(by_mmsi)
        static_data: Dict[str, Dict[str, Optional[str]]] = {}
        latest_positions: Dict[str, Position] = {
            mmsi: initial_positions[vessel.name.casefold()]
            for mmsi, vessel in by_mmsi.items()
            if vessel.name.casefold() in initial_positions
        }
        delay = 1
        while True:
            try:
                _notify_health(
                    on_health,
                    "connecting",
                    websocket_status="connecting",
                    subscription_status="not_sent",
                )
                async with websockets.connect(AISSTREAM_URL, open_timeout=10) as websocket:
                    LOGGER.info("AISstream WebSocket connected")
                    _notify_health(
                        on_health,
                        "waiting_for_subscription",
                        websocket_status="connected",
                        subscription_status="pending",
                    )
                    offset = 0
                    await _send_subscription(websocket, self.api_key, all_mmsis, offset)
                    loop = asyncio.get_running_loop()
                    next_rotation = (
                        loop.time() + SUBSCRIPTION_ROTATION_SECONDS
                        if len(all_mmsis) > MAX_MMSIS_PER_SUBSCRIPTION
                        else None
                    )
                    _notify_health(
                        on_health,
                        "waiting_for_data",
                        websocket_status="connected",
                        subscription_status="awaiting_first_frame",
                    )
                    delay = 1
                    while True:
                        receive_deadline = (
                            min(next_rotation, loop.time() + NO_FRAME_WARNING_SECONDS)
                            if next_rotation is not None
                            else loop.time() + NO_FRAME_WARNING_SECONDS
                        )
                        try:
                            payload = await asyncio.wait_for(
                                websocket.recv(),
                                timeout=max(0, receive_deadline - loop.time()),
                            )
                        except asyncio.TimeoutError:
                            LOGGER.warning(
                                "AISstream delivered no raw WebSocket frames in %.0f seconds; "
                                "socket remains connected and subscription acceptance is unconfirmed",
                                NO_FRAME_WARNING_SECONDS,
                            )
                            if next_rotation is not None and loop.time() >= next_rotation:
                                offset = _next_window_offset(offset, len(all_mmsis))
                                await _send_subscription(
                                    websocket, self.api_key, all_mmsis, offset
                                )
                                next_rotation = loop.time() + SUBSCRIPTION_ROTATION_SECONDS
                            continue
                        safe_raw = _redact(payload, self.api_key)
                        LOGGER.info(
                            "AISstream raw WebSocket frame received: bytes=%d payload=%s",
                            len(payload),
                            safe_raw[:RAW_FRAME_LOG_LIMIT],
                        )
                        message = json.loads(payload)
                        received_at = datetime.now(timezone.utc).isoformat()
                        if "error" in message:
                            safe_server_error = _redact(str(message["error"]), self.api_key)
                            LOGGER.error(
                                "AISstream subscription rejected/error response: %s",
                                safe_server_error,
                            )
                            _notify_health(
                                on_health,
                                "error",
                                safe_server_error,
                                websocket_status="connected",
                                subscription_status="rejected",
                                last_raw_frame_received_at=received_at,
                            )
                            raise AISStreamError(safe_server_error)
                        if not message.get("MessageType"):
                            LOGGER.info(
                                "AISstream acknowledgement/status response received: %s",
                                safe_raw[:RAW_FRAME_LOG_LIMIT],
                            )
                            _notify_health(
                                on_health,
                                "waiting_for_data",
                                websocket_status="connected",
                                subscription_status="acknowledgement_received",
                                last_raw_frame_received_at=received_at,
                            )
                            continue
                        message_type = str(message.get("MessageType") or "unknown")
                        mmsi = _message_mmsi(message)
                        identity = _message_identity(message)
                        LOGGER.info(
                            "AIS message received: type=%s mmsi=%s vessel=%s",
                            message_type,
                            mmsi or "unknown",
                            identity or "unknown",
                        )
                        _notify_health(
                            on_health,
                            "waiting_for_tracked_position",
                            websocket_status="connected",
                            subscription_status="data_received",
                            last_raw_frame_received_at=received_at,
                            last_ais_message_received_at=received_at,
                        )
                        static = static_data_from_message(message)
                        if static is not None:
                            mmsi, details = static
                            static_data[mmsi] = details
                            existing = latest_positions.get(mmsi)
                            if existing is not None:
                                enriched = _enrich_position(existing, details)
                                latest_positions[mmsi] = enriched
                                on_position(enriched)
                                LOGGER.info(
                                    "SQLite position written with static data: mmsi=%s vessel=%s",
                                    mmsi,
                                    enriched.vessel_name,
                                )
                            continue
                        position = position_from_message(message, by_mmsi)
                        if position is not None:
                            position = _enrich_position(position, static_data.get(mmsi, {}))
                            latest_positions[mmsi] = position
                            LOGGER.info(
                                "Tracked vessel matched: mmsi=%s vessel=%s",
                                mmsi,
                                position.vessel_name,
                            )
                            on_position(position)
                            LOGGER.info(
                                "SQLite position written: mmsi=%s vessel=%s timestamp=%s",
                                mmsi,
                                position.vessel_name,
                                position.position_timestamp.isoformat(),
                            )
                            _notify_health(
                                on_health,
                                "healthy",
                                websocket_status="connected",
                                subscription_status="data_received",
                                last_raw_frame_received_at=received_at,
                                last_ais_message_received_at=received_at,
                                last_tracked_position_received_at=received_at,
                            )
                        else:
                            LOGGER.info(
                                "AIS message ignored: type=%s mmsi=%s tracked=%s",
                                message_type,
                                mmsi or "unknown",
                                mmsi in by_mmsi,
                            )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                safe_error = _redact(str(exc), self.api_key)
                LOGGER.error(
                    "AISstream error=%s; reconnecting in %s seconds",
                    safe_error,
                    delay,
                )
                _notify_health(
                    on_health,
                    "error",
                    safe_error,
                    websocket_status="disconnected",
                    subscription_status="not_sent",
                )
                await asyncio.sleep(delay)
                LOGGER.info("Reconnecting to AISstream")
                delay = min(delay * 2, 60)

    async def _fetch(self, vessels: Sequence[Vessel]) -> Dict[str, Position]:
        try:
            import websockets
        except ImportError as exc:
            raise AISStreamError(
                "The websockets package is required; run: python -m pip install -e ."
            ) from exc

        by_mmsi = {str(vessel.mmsi): vessel for vessel in vessels}
        all_mmsis = list(by_mmsi)
        positions: Dict[str, Position] = {}
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout_seconds

        async with websockets.connect(AISSTREAM_URL, open_timeout=10) as websocket:
            offset = 0
            await _send_subscription(websocket, self.api_key, all_mmsis, offset)
            next_rotation = (
                loop.time() + SUBSCRIPTION_ROTATION_SECONDS
                if len(all_mmsis) > MAX_MMSIS_PER_SUBSCRIPTION
                else None
            )
            while len(positions) < len(by_mmsi):
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                receive_timeout = (
                    min(remaining, max(0, next_rotation - loop.time()))
                    if next_rotation is not None
                    else remaining
                )
                try:
                    payload = await asyncio.wait_for(
                        websocket.recv(), timeout=receive_timeout
                    )
                except asyncio.TimeoutError:
                    if next_rotation is None or loop.time() >= deadline:
                        break
                    offset = _next_window_offset(offset, len(all_mmsis))
                    await _send_subscription(
                        websocket, self.api_key, all_mmsis, offset
                    )
                    next_rotation = loop.time() + SUBSCRIPTION_ROTATION_SECONDS
                    continue
                message = json.loads(payload)
                position = position_from_message(message, by_mmsi)
                if position is not None:
                    positions[position.vessel_name.casefold()] = position
        return positions


def build_subscription(api_key: str, mmsis: Sequence[str]) -> Dict[str, Any]:
    if not api_key or not api_key.strip():
        raise AISStreamError("AISSTREAM_API_KEY is missing or empty")
    unique_mmsis = list(dict.fromkeys(str(mmsi) for mmsi in mmsis))
    if len(unique_mmsis) > MAX_MMSIS_PER_SUBSCRIPTION:
        raise AISStreamError(
            f"AISstream.io supports at most {MAX_MMSIS_PER_SUBSCRIPTION} "
            "MMSIs per subscription"
        )
    return {
        "APIKey": api_key.strip(),
        "BoundingBoxes": WORLD_BOUNDING_BOX,
        "FiltersShipMMSI": unique_mmsis,
        "FilterMessageTypes": list(SUBSCRIPTION_MESSAGE_TYPES),
    }


def subscription_window(
    mmsis: Sequence[str],
    offset: int = 0,
) -> list[str]:
    unique = list(dict.fromkeys(str(mmsi) for mmsi in mmsis))
    if len(unique) <= MAX_MMSIS_PER_SUBSCRIPTION:
        return unique
    start = offset % len(unique)
    return [
        unique[(start + index) % len(unique)]
        for index in range(MAX_MMSIS_PER_SUBSCRIPTION)
    ]


async def _send_subscription(
    websocket,
    api_key: str,
    mmsis: Sequence[str],
    offset: int,
) -> None:
    window = subscription_window(mmsis, offset)
    subscription = build_subscription(api_key, window)
    await websocket.send(json.dumps(subscription))
    LOGGER.info(
        "AISstream subscription JSON sent (acceptance unconfirmed): %s",
        json.dumps({**subscription, "APIKey": "[REDACTED]"}, separators=(",", ":")),
    )


def _redact(value: Any, api_key: str) -> str:
    text = str(value)
    return text.replace(api_key, "[REDACTED]") if api_key else text


def _next_window_offset(offset: int, vessel_count: int) -> int:
    if vessel_count <= MAX_MMSIS_PER_SUBSCRIPTION:
        return 0
    return (offset + vessel_count - MAX_MMSIS_PER_SUBSCRIPTION) % vessel_count


def _configured_by_mmsi(vessels: Sequence[Vessel]) -> Dict[str, Vessel]:
    return {
        str(vessel.mmsi): vessel
        for vessel in vessels
        if vessel.active and vessel.mmsi
    }


def position_from_message(
    message: Dict[str, Any], vessels_by_mmsi: Dict[str, Vessel]
) -> Optional[Position]:
    message_type = message.get("MessageType")
    if message_type not in POSITION_MESSAGE_TYPES:
        return None
    body = message.get("Message", {}).get(message_type, {})
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


def _message_mmsi(message: Dict[str, Any]) -> str:
    message_type = message.get("MessageType")
    body = message.get("Message", {}).get(message_type, {})
    metadata = message.get("MetaData") or message.get("Metadata") or {}
    return str(body.get("UserID") or metadata.get("MMSI") or "")


def _message_identity(message: Dict[str, Any]) -> str:
    metadata = message.get("MetaData") or message.get("Metadata") or {}
    message_type = message.get("MessageType")
    body = message.get("Message", {}).get(message_type, {})
    return str(metadata.get("ShipName") or body.get("Name") or "").strip(" @")


def _notify_health(
    callback: Optional[Callable[..., None]],
    status: str,
    error: Optional[str] = None,
    **details: Any,
) -> None:
    if callback is None:
        return
    try:
        callback(status, error, **details)
    except TypeError:
        # Keep third-party/two-argument callbacks compatible.
        callback(status, error)


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

#!/usr/bin/env python3
"""Run bounded AISstream subscription probes without exposing the API key."""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Iterable

import websockets

from fleet_receipt.config import PROJECT_ROOT, load_fleet
from fleet_receipt.providers.aisstream import (
    AISSTREAM_URL,
    MAX_MMSIS_PER_SUBSCRIPTION,
    WORLD_BOUNDING_BOX,
    _load_api_key,
    _redact,
)

DEFAULT_MMSI = "245464000"  # Rotterdam


def _subscription(
    api_key: str,
    message_types: list[str],
    mmsis: list[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "APIKey": api_key,
        "BoundingBoxes": WORLD_BOUNDING_BOX,
        "FilterMessageTypes": message_types,
    }
    if mmsis is not None:
        payload["FiltersShipMMSI"] = mmsis
    return payload


def _redacted_json(payload: dict[str, Any]) -> str:
    return json.dumps(
        {**payload, "APIKey": "[REDACTED]"},
        separators=(",", ":"),
    )


def _batches(values: list[str]) -> Iterable[list[str]]:
    for start in range(0, len(values), MAX_MMSIS_PER_SUBSCRIPTION):
        yield values[start : start + MAX_MMSIS_PER_SUBSCRIPTION]


async def _probe(
    label: str,
    payload: dict[str, Any],
    api_key: str,
    timeout: float,
    max_frames: int,
) -> bool:
    print(f"\n=== {label} ===", flush=True)
    print(f"endpoint={AISSTREAM_URL}", flush=True)
    print(f"subscription={_redacted_json(payload)}", flush=True)
    received = 0
    try:
        async with websockets.connect(
            AISSTREAM_URL,
            open_timeout=10,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=10,
            max_size=None,
        ) as websocket:
            await websocket.send(json.dumps(payload))
            while received < max_frames:
                try:
                    raw = await asyncio.wait_for(websocket.recv(), timeout=timeout)
                except asyncio.TimeoutError:
                    print(
                        f"RESULT label={label!r} frames={received} "
                        f"timeout_seconds={timeout} socket_open=true",
                        flush=True,
                    )
                    return received > 0
                received += 1
                safe_raw = _redact(raw, api_key)
                print(
                    f"RAW_FRAME {received}/{max_frames} bytes={len(raw)} "
                    f"payload={safe_raw}",
                    flush=True,
                )
                try:
                    decoded = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if "error" in decoded:
                    print(
                        "SERVER_ERROR=" + _redact(decoded["error"], api_key),
                        flush=True,
                    )
                    return False
            print(
                f"RESULT label={label!r} frames={received} success=true",
                flush=True,
            )
            return True
    except Exception as exc:
        print(
            f"RESULT label={label!r} connection_error={type(exc).__name__}: "
            f"{_redact(exc, api_key)}",
            flush=True,
        )
        return False


async def _run(args: argparse.Namespace) -> int:
    api_key = _load_api_key(Path(args.env_file))
    fleet = load_fleet(profile="all")
    all_mmsis = list(
        dict.fromkeys(
            str(vessel.mmsi)
            for vessel in fleet.vessels
            if vessel.active and vessel.mmsi
        )
    )
    batches = list(_batches(all_mmsis))
    print(
        f"AISstream staged diagnostic: tracked_mmsis={len(all_mmsis)} "
        f"valid_batches={len(batches)} max_batch_size={MAX_MMSIS_PER_SUBSCRIPTION}",
        flush=True,
    )

    stages: list[tuple[str, dict[str, Any]]] = [
        (
            "A worldwide PositionReport only (no MMSI filter)",
            _subscription(api_key, ["PositionReport"]),
        ),
        (
            f"B worldwide PositionReport + one MMSI {args.mmsi}",
            _subscription(api_key, ["PositionReport"], [args.mmsi]),
        ),
    ]
    for index, batch in enumerate(batches, 1):
        stages.append(
            (
                f"C worldwide PositionReport + tracked batch {index}/{len(batches)}",
                _subscription(api_key, ["PositionReport"], batch),
            )
        )
    for index, batch in enumerate(batches, 1):
        stages.append(
            (
                f"D add StandardClassBPositionReport batch {index}/{len(batches)}",
                _subscription(
                    api_key,
                    ["PositionReport", "StandardClassBPositionReport"],
                    batch,
                ),
            )
        )
    for index, batch in enumerate(batches, 1):
        stages.append(
            (
                f"E add ShipStaticData batch {index}/{len(batches)}",
                _subscription(
                    api_key,
                    [
                        "PositionReport",
                        "StandardClassBPositionReport",
                        "ShipStaticData",
                    ],
                    batch,
                ),
            )
        )

    if args.stage != "all":
        prefix = args.stage.upper() + " "
        stages = [(label, payload) for label, payload in stages if label.startswith(prefix)]

    results = []
    for label, payload in stages:
        results.append(
            (
                label,
                await _probe(label, payload, api_key, args.timeout, args.frames),
            )
        )
    print("\n=== SUMMARY ===", flush=True)
    for label, success in results:
        print(f"{'PASS' if success else 'NO DATA'}: {label}", flush=True)
    return 0 if results[0][1] else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mmsi", default=DEFAULT_MMSI)
    parser.add_argument("--frames", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--stage",
        choices=("all", "a", "b", "c", "d", "e"),
        default="all",
        help="Run every progressive stage or only one lettered stage",
    )
    parser.add_argument("--env-file", default=str(PROJECT_ROOT / ".env"))
    args = parser.parse_args()
    if not 1 <= args.frames <= 10:
        parser.error("--frames must be between 1 and 10")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())

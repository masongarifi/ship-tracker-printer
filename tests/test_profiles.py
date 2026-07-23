from datetime import datetime, timedelta, timezone
import json

import pytest

from fleet_receipt import cli
from fleet_receipt.cache import PositionCache
from fleet_receipt.config import ConfigurationError, load_fleet
from fleet_receipt.models import Position, Vessel
from fleet_receipt.providers.aisstream import (
    AISStreamError,
    AISStreamProvider,
    build_subscription,
    subscription_window,
)
from fleet_receipt.reporting import render_cached_report


NOW = datetime(2026, 7, 23, 16, 0, tzinfo=timezone.utc)
CELEBRITY_MMSIS = {
    "215105000",
    "256191000",
    "215808000",
    "249046000",
    "249666000",
    "248325000",
    "249667000",
    "735059945",
    "249048000",
    "249055000",
    "229074000",
    "248939000",
    "249409000",
    "249047000",
    "249457000",
}
ROYAL_CARIBBEAN_MMSIS = {
    "311263000",
    "311020700",
    "311000274",
    "311361000",
    "311733000",
    "311316000",
    "309906000",
    "311315000",
    "311000396",
    "311001178",
    "309374000",
    "311583000",
    "311001716",
    "309436000",
    "311493000",
    "311478000",
    "311020600",
    "311000912",
    "311000397",
    "311000267",
    "311319000",
    "311805000",
    "311492000",
    "311000749",
    "311001551",
    "311000660",
    "311001259",
    "311321000",
    "311317000",
    "311001033",
}


def _position(name: str, timestamp: datetime = NOW) -> Position:
    return Position(
        vessel_name=name,
        latitude=50.0,
        longitude=-2.0,
        speed_knots=14.0,
        course_degrees=75.0,
        navigational_status="Under way",
        destination="GB DVR",
        reported_eta=None,
        position_timestamp=timestamp,
        source="AISstream.io",
    )


def test_celebrity_fleet_configuration_loads_all_active_ships() -> None:
    fleet = load_fleet(profile="celebrity")

    assert fleet.cruise_line_order == ("Celebrity Cruises",)
    assert len(fleet.vessels) == 15
    assert {vessel.mmsi for vessel in fleet.vessels} == CELEBRITY_MMSIS
    assert all(vessel.active for vessel in fleet.vessels)
    assert {vessel.name for vessel in fleet.vessels} >= {
        "Celebrity Apex",
        "Celebrity Xcel",
    }


def test_all_configured_mmsis_are_in_one_listener_subscription() -> None:
    fleet = load_fleet(profile="all")
    mmsis = [vessel.mmsi for vessel in fleet.vessels if vessel.active and vessel.mmsi]

    windows = []
    offset = 0
    for _ in range(5):
        windows.append(subscription_window(mmsis, offset))
        offset = (offset + len(mmsis) - 50) % len(mmsis)

    assert len(mmsis) == 208
    assert all(len(window) == 50 for window in windows)
    assert set(mmsis) == set().union(*map(set, windows))
    assert CELEBRITY_MMSIS <= set(mmsis)
    assert ROYAL_CARIBBEAN_MMSIS <= set(mmsis)
    with pytest.raises(AISStreamError, match="at most 50"):
        build_subscription("secret", mmsis)


def test_listener_deduplicates_mmsis_across_fleets(monkeypatch) -> None:
    provider = AISStreamProvider(api_key="secret")
    captured = []

    async def capture(vessels, on_position, on_health, initial_positions):
        captured.extend(vessels)

    monkeypatch.setattr(provider, "_listen_forever", capture)
    duplicate_mmsi = [
        Vessel("Fleet One", "Ship One", mmsi="123456789"),
        Vessel("Fleet Two", "Ship Two", mmsi="123456789"),
    ]

    provider.listen_forever(duplicate_mmsi, lambda position: None)

    assert len(captured) == 1
    assert captured[0].mmsi == "123456789"
    assert build_subscription(
        "secret", ["123456789", "123456789"]
    )["FiltersShipMMSI"] == ["123456789"]


def test_listener_loads_every_profile(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SHIP_TRACKER_DATA_DIR", str(tmp_path / "app-data"))
    received_mmsis = set()

    class FakeProvider:
        def listen_forever(
            self,
            vessels,
            on_position,
            on_health,
            initial_positions,
        ):
            received_mmsis.update(vessel.mmsi for vessel in vessels)
            raise KeyboardInterrupt

    monkeypatch.setattr(cli, "AISStreamProvider", FakeProvider)
    monkeypatch.setattr(cli, "unlocode_available", lambda: True)

    assert cli.main(["listen"]) == 130
    assert CELEBRITY_MMSIS <= received_mmsis
    assert ROYAL_CARIBBEAN_MMSIS <= received_mmsis
    assert len(received_mmsis) == 208


def test_celebrity_cached_preview_filters_shared_cache(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "app-data"
    monkeypatch.setenv("SHIP_TRACKER_DATA_DIR", str(data_dir))
    cache = PositionCache(data_dir / "ais-cache.sqlite3")
    cache.update(_position("Celebrity Apex"))
    cache.update(_position("Eurodam"))
    output = tmp_path / "celebrity.txt"

    result = cli.main(
        [
            "preview",
            "--cached",
            "--fleet",
            "celebrity",
            "--at",
            NOW.isoformat(),
            "--output",
            str(output),
        ]
    )

    assert result == 0
    report = output.read_text(encoding="utf-8")
    assert "Celebrity Reporting: 1 / 15" in report
    assert "CELEBRITY APEX" in report
    assert "EURODAM" not in report


def test_celebrity_missing_and_stale_positions_use_existing_states(tmp_path) -> None:
    cache = PositionCache(tmp_path / "ais-cache.sqlite3")
    cache.update(_position("Celebrity Apex", NOW - timedelta(hours=18)))

    report = render_cached_report(
        cache,
        generated_at=NOW,
        fleet_profile="celebrity",
    )

    assert "Celebrity Reporting: 1 / 15" in report
    assert "CELEBRITY APEX" in report
    assert "Last AIS report 18 hours ago" in report
    assert "NO RECENT AIS (14)" in report


def test_all_report_groups_every_configured_fleet(tmp_path) -> None:
    cache = PositionCache(tmp_path / "ais-cache.sqlite3")

    report = render_cached_report(cache, generated_at=NOW, fleet_profile="all")

    assert "HAL Reporting: 0 / 11" in report
    assert "Seabourn Reporting: 0 / 5" in report
    assert "Celebrity Reporting: 0 / 15" in report
    assert "Royal Caribbean Reporting: 0 / 30" in report
    assert "HOLLAND AMERICA LINE" in report
    assert "SEABOURN" in report
    assert "CELEBRITY CRUISES" in report
    assert "ROYAL CARIBBEAN INTERNATIONAL" in report
    assert report.index("EURODAM") < report.index("SEABOURN ENCORE")
    assert report.index("SEABOURN ENCORE") < report.index("CELEBRITY APEX")
    assert report.index("CELEBRITY APEX") < report.index("ADVENTURE OF THE SEAS")


def test_royal_caribbean_configuration_has_all_30_ships_in_order() -> None:
    fleet = load_fleet(profile="royal-caribbean")
    names = [vessel.name for vessel in fleet.vessels]

    assert fleet.cruise_line_order == ("Royal Caribbean International",)
    assert len(fleet.vessels) == 30
    assert {vessel.mmsi for vessel in fleet.vessels} == ROYAL_CARIBBEAN_MMSIS
    assert names == sorted(names, key=str.casefold)
    assert all(vessel.active for vessel in fleet.vessels)


def test_royal_caribbean_cached_preview_uses_shared_cache(
    tmp_path, monkeypatch
) -> None:
    data_dir = tmp_path / "app-data"
    monkeypatch.setenv("SHIP_TRACKER_DATA_DIR", str(data_dir))
    cache = PositionCache(data_dir / "ais-cache.sqlite3")
    cache.update(_position("Adventure of the Seas"))
    cache.update(_position("Celebrity Apex"))
    output = tmp_path / "royal-caribbean.txt"

    result = cli.main(
        [
            "preview",
            "--cached",
            "--fleet",
            "royal-caribbean",
            "--at",
            NOW.isoformat(),
            "--output",
            str(output),
        ]
    )

    report = output.read_text(encoding="utf-8")
    assert result == 0
    assert "Royal Caribbean Reporting: 1 / 30" in report
    assert "ADVENTURE OF THE SEAS" in report
    assert "CELEBRITY APEX" not in report


def test_royal_caribbean_missing_and_stale_positions(tmp_path) -> None:
    cache = PositionCache(tmp_path / "ais-cache.sqlite3")
    cache.update(_position("Adventure of the Seas", NOW - timedelta(hours=18)))

    report = render_cached_report(
        cache,
        generated_at=NOW,
        fleet_profile="royal-caribbean",
    )

    assert "Royal Caribbean Reporting: 1 / 30" in report
    assert "Last AIS report 18 hours ago" in report
    assert "NO RECENT AIS (29)" in report


def test_cli_accepts_hyphenated_royal_caribbean_profile() -> None:
    args = cli.build_parser().parse_args(
        ["preview", "--cached", "--fleet", "royal-caribbean"]
    )

    assert args.fleet == "royal-caribbean"


@pytest.mark.parametrize(
    ("vessels", "message"),
    [
        (
            [
                {"name": "Ship One", "imo": "9167227", "mmsi": "311263000"},
                {"name": "Ship Two", "imo": "9383948", "mmsi": "311263000"},
            ],
            "Duplicate MMSI",
        ),
        (
            [
                {"name": "Ship One", "imo": "9167227", "mmsi": "311263000"},
                {"name": "Ship Two", "imo": "9167227", "mmsi": "311020700"},
            ],
            "Duplicate IMO",
        ),
        (
            [{"name": "Ship One", "imo": "9167227", "mmsi": "123"}],
            "Malformed MMSI",
        ),
        (
            [{"name": "Ship One", "imo": "1234560", "mmsi": "311263000"}],
            "Malformed IMO",
        ),
        (
            [{"imo": "9167227", "mmsi": "311263000"}],
            "no name",
        ),
    ],
)
def test_fleet_validation_rejects_invalid_vessel_identifiers(
    tmp_path, vessels, message
) -> None:
    config_path = tmp_path / "fleet.yaml"
    config_path.write_text(
        json.dumps(
            {
                "cruise_lines": [
                    {
                        "name": "Test Fleet",
                        "profile": "test-fleet",
                        "vessels": vessels,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match=message):
        load_fleet(config_path, profile="test-fleet")

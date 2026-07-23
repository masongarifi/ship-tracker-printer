from datetime import datetime, timedelta, timezone

from fleet_receipt import cli
from fleet_receipt.cache import PositionCache
from fleet_receipt.config import load_fleet
from fleet_receipt.models import Position, Vessel
from fleet_receipt.providers.aisstream import AISStreamProvider, build_subscription
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

    subscription = build_subscription("secret", mmsis)

    assert len(subscription["FiltersShipMMSI"]) == 31
    assert CELEBRITY_MMSIS <= set(subscription["FiltersShipMMSI"])
    assert "245206000" in subscription["FiltersShipMMSI"]
    assert "311000464" in subscription["FiltersShipMMSI"]


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
    assert len(received_mmsis) == 31


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
    assert "HOLLAND AMERICA LINE" in report
    assert "SEABOURN" in report
    assert "CELEBRITY CRUISES" in report
    assert report.index("EURODAM") < report.index("SEABOURN ENCORE")
    assert report.index("SEABOURN ENCORE") < report.index("CELEBRITY APEX")

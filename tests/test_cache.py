import json
import sqlite3
from datetime import datetime, timezone

from fleet_receipt.cache import PositionCache, default_cache_path
from fleet_receipt.models import Position


def make_position(name, latitude, timestamp=None):
    return Position(
        vessel_name=name,
        latitude=latitude,
        longitude=-122.3,
        speed_knots=10.0,
        course_degrees=90.0,
        navigational_status="Under way",
        destination=None,
        reported_eta=None,
        position_timestamp=timestamp
        or datetime(2026, 7, 23, tzinfo=timezone.utc),
        source="AISstream.io",
    )


def test_cache_survives_restart_and_is_immediately_available(tmp_path):
    path = tmp_path / "ais-cache.sqlite3"
    first_process = PositionCache(path)
    first_process.update(make_position("Eurodam", 47.6))

    restarted_process = PositionCache(path)
    loaded_at_startup = restarted_process.load()

    assert loaded_at_startup["eurodam"].latitude == 47.6


def test_new_update_overwrites_only_affected_vessel(tmp_path):
    path = tmp_path / "ais-cache.sqlite3"
    cache = PositionCache(path)
    cache.update(make_position("Eurodam", 47.6))
    cache.update(make_position("Koningsdam", 48.1))
    cache.update(make_position("Eurodam", 49.0))

    loaded = PositionCache(path).load()

    assert set(loaded) == {"eurodam", "koningsdam"}
    assert loaded["eurodam"].latitude == 49.0
    assert loaded["koningsdam"].latitude == 48.1


def test_cache_path_survives_checkout_or_software_update(tmp_path, monkeypatch):
    data_home = tmp_path / "persistent-data"
    old_checkout = tmp_path / "checkout-v1"
    new_checkout = tmp_path / "checkout-v2"
    old_checkout.mkdir()
    new_checkout.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.delenv("SHIP_TRACKER_DATA_DIR", raising=False)

    monkeypatch.chdir(old_checkout)
    before_update = PositionCache()
    before_update.update(make_position("Eurodam", 47.6))

    monkeypatch.chdir(new_checkout)
    after_update = PositionCache()

    assert after_update.path == data_home / "ship-tracker-printer" / "ais-cache.sqlite3"
    assert after_update.load()["eurodam"].latitude == 47.6
    assert old_checkout not in after_update.path.parents
    assert new_checkout not in after_update.path.parents


def test_default_linux_data_location_uses_xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.delenv("SHIP_TRACKER_DATA_DIR", raising=False)

    assert default_cache_path() == (
        tmp_path / "ship-tracker-printer" / "ais-cache.sqlite3"
    )


def test_sqlite_integrity_and_health_survive_reopen(tmp_path):
    path = tmp_path / "ais-cache.sqlite3"
    cache = PositionCache(path)
    cache.update(make_position("Eurodam", 47.6))
    cache.update_health("connected")

    reopened = PositionCache(path)
    with sqlite3.connect(path) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]

    assert integrity == "ok"
    assert reopened.health()["status"] == "connected"


def test_legacy_repository_json_is_migrated_once(tmp_path):
    legacy_path = tmp_path / "position-cache.json"
    database_path = tmp_path / "persistent" / "ais-cache.sqlite3"
    position = make_position("Eurodam", 47.6)
    legacy_path.write_text(
        json.dumps(
            {
                "positions": {
                    "eurodam": {
                        "vessel_name": position.vessel_name,
                        "latitude": position.latitude,
                        "longitude": position.longitude,
                        "speed_knots": position.speed_knots,
                        "course_degrees": position.course_degrees,
                        "navigational_status": position.navigational_status,
                        "destination": None,
                        "reported_eta": None,
                        "position_timestamp": position.position_timestamp.isoformat(),
                        "source": position.source,
                    }
                },
                "health": {"source": "Terrestrial", "status": "connected"},
            }
        ),
        encoding="utf-8",
    )

    migrated = PositionCache(database_path, legacy_path=legacy_path)

    assert migrated.load()["eurodam"].latitude == 47.6
    assert migrated.health()["status"] == "connected"
    assert legacy_path.exists()


def test_missing_cache_starts_empty(tmp_path):
    assert PositionCache(tmp_path / "missing.sqlite3").load() == {}

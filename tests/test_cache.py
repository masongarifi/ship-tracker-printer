from datetime import datetime, timezone

from fleet_receipt.cache import PositionCache
from fleet_receipt.models import Position


def make_position(name, latitude):
    return Position(
        vessel_name=name,
        latitude=latitude,
        longitude=-122.3,
        speed_knots=10.0,
        course_degrees=90.0,
        navigational_status="Under way",
        destination=None,
        reported_eta=None,
        position_timestamp=datetime(2026, 7, 23, tzinfo=timezone.utc),
        source="AISstream.io",
    )


def test_cache_updates_one_vessel_without_losing_others(tmp_path):
    cache = PositionCache(tmp_path / "positions.json")
    cache.update(make_position("Eurodam", 47.6))
    cache.update(make_position("Koningsdam", 48.1))
    cache.update(make_position("Eurodam", 49.0))

    loaded = cache.load()

    assert set(loaded) == {"eurodam", "koningsdam"}
    assert loaded["eurodam"].latitude == 49.0
    assert loaded["koningsdam"].latitude == 48.1


def test_missing_cache_is_an_empty_snapshot(tmp_path):
    assert PositionCache(tmp_path / "missing.json").load() == {}

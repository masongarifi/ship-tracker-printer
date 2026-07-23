from datetime import datetime, timezone

from fleet_receipt import cli
from fleet_receipt.cache import PositionCache
from fleet_receipt.models import Position


def test_listener_receives_persistent_positions_immediately_at_startup(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SHIP_TRACKER_DATA_DIR", str(tmp_path / "app-data"))
    cache = PositionCache()
    cache.update(
        Position(
            vessel_name="Eurodam",
            latitude=47.6,
            longitude=-122.3,
            speed_knots=10.0,
            course_degrees=90.0,
            navigational_status="Under way",
            destination=None,
            reported_eta=None,
            position_timestamp=datetime(2026, 7, 23, tzinfo=timezone.utc),
            source="AISstream.io",
        )
    )
    received = {}

    class FakeProvider:
        def listen_forever(
            self,
            vessels,
            on_position,
            on_health,
            initial_positions,
        ):
            received.update(initial_positions)
            raise KeyboardInterrupt

    monkeypatch.setattr(cli, "AISStreamProvider", FakeProvider)

    assert cli.main(["listen"]) == 130
    assert received["eurodam"].latitude == 47.6

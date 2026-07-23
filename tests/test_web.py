from datetime import datetime, timedelta, timezone
from html import escape

from fastapi.testclient import TestClient

from fleet_receipt.cache import PositionCache
from fleet_receipt.cli import build_parser
from fleet_receipt.models import Position
from fleet_receipt.reporting import render_cached_report
from fleet_receipt.web import create_app


NOW = datetime(2026, 7, 23, 16, 0, tzinfo=timezone.utc)


def _position(
    *,
    vessel_name: str = "Koningsdam",
    received_at: datetime | None = None,
    destination: str | None = "NL RTM",
) -> Position:
    return Position(
        vessel_name=vessel_name,
        latitude=52.0,
        longitude=3.5,
        speed_knots=15.2,
        course_degrees=87.0,
        navigational_status="Underway",
        destination=destination,
        reported_eta=None,
        position_timestamp=received_at or NOW - timedelta(minutes=3),
        source="AISstream.io",
    )


def _client(cache: PositionCache) -> TestClient:
    return TestClient(create_app(cache=cache, now_factory=lambda: NOW))


def test_web_cli_defaults() -> None:
    args = build_parser().parse_args(["web"])

    assert args.host == "0.0.0.0"
    assert args.port == 8000


def test_main_page_renders_receipt(tmp_path) -> None:
    cache = PositionCache(tmp_path / "positions.sqlite3")
    cache.update(_position())
    expected = render_cached_report(cache, generated_at=NOW)

    response = _client(cache).get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<title>Fleet Operations Brief</title>" in response.text
    assert '<meta http-equiv="refresh" content="30">' in response.text
    assert "<pre" in response.text
    assert "Page refreshed:" in response.text
    assert escape(expected) in response.text


def test_web_uses_positions_from_persistent_cache(tmp_path) -> None:
    cache_path = tmp_path / "positions.sqlite3"
    first_process_cache = PositionCache(cache_path)
    first_process_cache.update(_position())

    restarted_process_cache = PositionCache(cache_path)
    response = _client(restarted_process_cache).get("/")

    assert response.status_code == 200
    assert "KONINGSDAM" in response.text
    assert "52°00.0&#x27;N 003°30.0&#x27;E" in response.text


def test_plain_text_report_matches_shared_renderer(tmp_path) -> None:
    cache = PositionCache(tmp_path / "positions.sqlite3")
    cache.update(_position())
    expected = render_cached_report(cache, generated_at=NOW)

    response = _client(cache).get("/api/report")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == expected


def test_health_reports_cache_summary(tmp_path) -> None:
    cache = PositionCache(tmp_path / "positions.sqlite3")
    cache.update(_position(received_at=NOW - timedelta(minutes=12)))
    cache.update(
        _position(
            vessel_name="Nieuw Statendam",
            received_at=NOW - timedelta(minutes=5),
        )
    )

    response = _client(cache).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "cache_database_available": True,
        "cached_vessels": 2,
        "newest_ais_update": "2026-07-23T15:55:00+00:00",
        "newest_ais_update_age_seconds": 300,
    }


def test_empty_cache_is_served_without_error(tmp_path) -> None:
    cache = PositionCache(tmp_path / "positions.sqlite3")
    client = _client(cache)

    page_response = client.get("/")
    report_response = client.get("/api/report")
    health_response = client.get("/health")

    assert page_response.status_code == 200
    assert "NO RECENT AIS" in page_response.text
    assert report_response.status_code == 200
    assert "NO RECENT AIS" in report_response.text
    assert health_response.json() == {
        "status": "ok",
        "cache_database_available": True,
        "cached_vessels": 0,
        "newest_ais_update": None,
        "newest_ais_update_age_seconds": None,
    }


def test_vessel_data_is_html_escaped(tmp_path) -> None:
    cache = PositionCache(tmp_path / "positions.sqlite3")
    cache.update(_position(destination="<script>alert(1)</script>"))

    response = _client(cache).get("/")

    assert response.status_code == 200
    assert "<script" not in response.text.casefold()
    assert "&lt;script" in response.text.casefold()
    assert "&lt;/script&gt;" in response.text.casefold()
    assert "AISSTREAM_API_KEY" not in response.text
    assert str(cache.path) not in response.text


def test_celebrity_routes_render_only_celebrity_report(tmp_path) -> None:
    cache = PositionCache(tmp_path / "positions.sqlite3")
    cache.update(_position(vessel_name="Celebrity Apex"))
    cache.update(_position(vessel_name="Eurodam"))
    client = _client(cache)

    for route in ("/celebrity", "/profile/celebrity"):
        response = client.get(route)
        assert response.status_code == 200
        assert "Celebrity Cruises" in response.text
        assert "CELEBRITY APEX" in response.text
        assert "EURODAM" not in response.text
        assert '<meta http-equiv="refresh" content="30">' in response.text


def test_main_page_links_to_celebrity_without_changing_default_report(tmp_path) -> None:
    cache = PositionCache(tmp_path / "positions.sqlite3")
    cache.update(_position(vessel_name="Celebrity Apex"))

    response = _client(cache).get("/")

    assert response.status_code == 200
    assert '<a href="/celebrity">Celebrity</a>' in response.text
    assert "Celebrity Reporting:" not in response.text
    assert "CELEBRITY APEX" not in response.text


def test_all_page_groups_main_and_celebrity_fleets(tmp_path) -> None:
    cache = PositionCache(tmp_path / "positions.sqlite3")
    cache.update(_position(vessel_name="Koningsdam"))
    cache.update(_position(vessel_name="Celebrity Apex"))

    response = _client(cache).get("/all")

    assert response.status_code == 200
    assert "HAL Reporting: 1 / 11" in response.text
    assert "Seabourn Reporting: 0 / 5" in response.text
    assert "Celebrity Reporting: 1 / 15" in response.text
    assert response.text.index("KONINGSDAM") < response.text.index("CELEBRITY APEX")


def test_royal_caribbean_routes_render_shared_cached_report(tmp_path) -> None:
    cache = PositionCache(tmp_path / "positions.sqlite3")
    cache.update(_position(vessel_name="Adventure of the Seas"))
    cache.update(_position(vessel_name="Celebrity Apex"))
    client = _client(cache)

    for route in ("/royal-caribbean", "/profile/royal-caribbean"):
        response = client.get(route)
        assert response.status_code == 200
        assert "Royal Caribbean International" in response.text
        assert "Royal Caribbean Reporting: 1 / 30" in response.text
        assert "ADVENTURE OF THE SEAS" in response.text
        assert "CELEBRITY APEX" not in response.text


def test_all_page_includes_royal_caribbean_group(tmp_path) -> None:
    cache = PositionCache(tmp_path / "positions.sqlite3")
    cache.update(_position(vessel_name="Adventure of the Seas"))

    response = _client(cache).get("/all")

    assert response.status_code == 200
    assert "Royal Caribbean Reporting: 1 / 30" in response.text
    assert "ROYAL CARIBBEAN INTERNATIONAL" in response.text
    assert '<a href="/royal-caribbean">Royal Caribbean</a>' in response.text

from datetime import datetime, timedelta, timezone
import json
import re
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


def test_main_page_renders_dashboard_from_cache(tmp_path) -> None:
    cache = PositionCache(tmp_path / "positions.sqlite3")
    cache.update(_position())

    response = _client(cache).get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<title>Fleet Tracker · Live Cruise Fleet Dashboard</title>" in response.text
    assert 'id="fleet-map"' in response.text
    assert "Holland America" in response.text
    assert "Royal Caribbean" in response.text
    assert "Fleet statistics" in response.text
    assert "/static/css/main.css" in response.text
    assert "/static/dashboard.js" in response.text


def test_web_uses_positions_from_persistent_cache(tmp_path) -> None:
    cache_path = tmp_path / "positions.sqlite3"
    first_process_cache = PositionCache(cache_path)
    first_process_cache.update(_position())

    restarted_process_cache = PositionCache(cache_path)
    response = _client(restarted_process_cache).get("/")

    assert response.status_code == 200
    assert "Koningsdam" in response.text
    assert '"latitude": 52.0' in response.text
    assert '"longitude": 3.5' in response.text


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
    assert "ships currently reporting" in page_response.text
    assert "Last AIS update" in page_response.text
    assert "Unavailable" in page_response.text
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
    assert "<script>alert(1)</script>" not in response.text.casefold()
    assert "\\u003cscript" in response.text.casefold()
    assert "\\u003c/script\\u003e" in response.text.casefold()
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


def test_main_page_links_to_celebrity_card(tmp_path) -> None:
    cache = PositionCache(tmp_path / "positions.sqlite3")
    cache.update(_position(vessel_name="Celebrity Apex"))

    response = _client(cache).get("/")

    assert response.status_code == 200
    assert 'href="http://testserver/celebrity"' in response.text
    assert "Celebrity Reporting:" not in response.text
    assert "Celebrity Apex" in response.text


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
    assert (
        '<a class="button button-secondary" href="/royal-caribbean">'
        "Royal Caribbean</a>"
    ) in response.text


def test_existing_hal_and_seabourn_receipt_routes_remain_separate(tmp_path) -> None:
    cache = PositionCache(tmp_path / "positions.sqlite3")
    cache.update(_position(vessel_name="Koningsdam"))
    cache.update(_position(vessel_name="Seabourn Quest"))
    client = _client(cache)

    hal = client.get("/hal")
    seabourn = client.get("/seabourn")

    assert hal.status_code == 200
    assert "HAL Reporting: 1 / 11" in hal.text
    assert "KONINGSDAM" in hal.text
    assert "SEABOURN QUEST" not in hal.text
    assert seabourn.status_code == 200
    assert "Seabourn Reporting: 1 / 5" in seabourn.text
    assert "SEABOURN QUEST" in seabourn.text
    assert "KONINGSDAM" not in seabourn.text


def test_receipt_navigation_uses_named_fleet_routes(tmp_path) -> None:
    cache = PositionCache(tmp_path / "positions.sqlite3")
    cache.update(_position(vessel_name="Koningsdam"))
    cache.update(_position(vessel_name="Seabourn Quest"))
    client = _client(cache)

    source_page = client.get("/celebrity")
    expected_links = {
        "HAL + Seabourn": "/hal-seabourn",
        "Celebrity": "/celebrity",
        "Royal Caribbean": "/royal-caribbean",
        "All Fleets": "/all",
    }

    for label, path in expected_links.items():
        assert re.search(
            rf'<a class="button button-secondary" href="{path}">{re.escape(label)}</a>',
            source_page.text,
        )

    combined = client.get(expected_links["HAL + Seabourn"])
    celebrity = client.get(expected_links["Celebrity"])
    royal_caribbean = client.get(expected_links["Royal Caribbean"])
    all_fleets = client.get(expected_links["All Fleets"])

    assert combined.status_code == 200
    assert "HAL Reporting: 1 / 11" in combined.text
    assert "Seabourn Reporting: 1 / 5" in combined.text
    assert "Celebrity Reporting:" not in combined.text
    assert celebrity.status_code == 200
    assert "Celebrity Reporting:" in celebrity.text
    assert royal_caribbean.status_code == 200
    assert "Royal Caribbean Reporting:" in royal_caribbean.text
    assert all_fleets.status_code == 200
    assert "HAL Reporting:" in all_fleets.text
    assert "Celebrity Reporting:" in all_fleets.text
    assert "Royal Caribbean Reporting:" in all_fleets.text


def test_landing_page_remains_at_root(tmp_path) -> None:
    response = _client(PositionCache(tmp_path / "positions.sqlite3")).get("/")

    assert response.status_code == 200
    assert "<title>Fleet Tracker · Live Cruise Fleet Dashboard</title>" in response.text
    assert "FLEET OPERATIONS BRIEF" not in response.text


def test_dashboard_map_contains_required_cached_ship_fields(tmp_path) -> None:
    cache = PositionCache(tmp_path / "positions.sqlite3")
    cache.update(_position(vessel_name="Koningsdam", destination="NL RTM"))

    response = _client(cache).get("/")

    assert response.status_code == 200
    for field in (
        '"name": "Koningsdam"',
        '"fleet": "Holland America Line"',
        '"status": "Underway"',
        '"speed": "15.2 kt"',
        '"course": "087',
        '"destination": "Rotterdam, Netherlands"',
        '"eta": "Unavailable"',
        '"details_url": "/ship/koningsdam"',
    ):
        assert field in response.text


def test_search_redirects_exact_identifier_and_lists_partial_matches(tmp_path) -> None:
    client = _client(PositionCache(tmp_path / "positions.sqlite3"))

    exact = client.get("/search?q=9692557", follow_redirects=False)
    partial = client.get("/search?q=Celebrity", follow_redirects=False)

    assert exact.status_code == 303
    assert exact.headers["location"] == "/ship/koningsdam"
    assert partial.status_code == 200
    assert "Celebrity Apex" in partial.text
    assert "Celebrity Xcel" in partial.text


def test_ship_detail_page_uses_cached_position(tmp_path) -> None:
    cache = PositionCache(tmp_path / "positions.sqlite3")
    cache.update(_position(vessel_name="Koningsdam"))

    response = _client(cache).get("/ship/koningsdam")

    assert response.status_code == 200
    assert "<h1>Koningsdam</h1>" in response.text
    assert "IMO" in response.text
    assert "9692557" in response.text
    assert "15.2 kt" in response.text
    assert "Last AIS update" in response.text


def test_dashboard_reads_cache_once_per_request(tmp_path) -> None:
    underlying = PositionCache(tmp_path / "positions.sqlite3")
    underlying.update(_position())

    class CountingCache:
        def __init__(self):
            self.loads = 0

        def load(self):
            self.loads += 1
            return underlying.load()

    cache = CountingCache()
    response = TestClient(create_app(cache=cache, now_factory=lambda: NOW)).get("/")

    assert response.status_code == 200
    assert cache.loads == 1


def test_shared_styles_and_dashboard_assets_are_served(tmp_path) -> None:
    client = _client(PositionCache(tmp_path / "positions.sqlite3"))

    css = client.get("/static/css/main.css")
    javascript = client.get("/static/dashboard.js")

    assert css.status_code == 200
    assert "--navy-950" in css.text
    assert javascript.status_code == 200
    assert "setInterval" not in javascript.text
    assert "fetch(" not in javascript.text
    assert 'document.addEventListener("DOMContentLoaded"' in javascript.text
    assert "mapElement.replaceChildren()" in javascript.text
    assert "map.invalidateSize" in javascript.text
    assert "ships.forEach" in javascript.text
    assert "try {" in javascript.text
    assert "map.setView([20, 0], 2)" in javascript.text
    assert "L.divIcon" in javascript.text
    assert "L.marker" in javascript.text
    assert "L.circleMarker" not in javascript.text
    assert "iconSize: [30, 30]" in javascript.text


def test_map_uses_exact_fleet_identifiers_and_emoji_fallback(tmp_path) -> None:
    javascript = _client(PositionCache(tmp_path / "positions.sqlite3")).get(
        "/static/dashboard.js"
    ).text

    expected_mapping = {
        "Holland America Line": "🚢",
        "Seabourn": "⚓",
        "Celebrity Cruises": "🌊",
        "Royal Caribbean International": "🛳️",
    }
    for fleet_name, emoji in expected_mapping.items():
        assert fleet_name in javascript
        assert emoji in javascript
    assert '|| "🚢"' in javascript
    assert "/static/img/fleets/" not in javascript
    assert "<img" not in javascript


def test_every_receipt_route_has_home_button_and_shared_design(tmp_path) -> None:
    client = _client(PositionCache(tmp_path / "positions.sqlite3"))
    routes = (
        "/hal-seabourn",
        "/hal",
        "/seabourn",
        "/celebrity",
        "/profile/celebrity",
        "/royal-caribbean",
        "/profile/royal-caribbean",
        "/all",
    )

    for route in routes:
        response = client.get(route)
        assert response.status_code == 200
        assert "← Fleet Tracker Home" in response.text
        assert 'href="http://testserver/"' in response.text
        assert "/static/css/main.css" in response.text
        assert 'class="site-header"' in response.text
        assert 'class="panel receipt-card"' in response.text
        assert 'aria-label="Fleet operations receipt"' in response.text


def test_all_html_pages_extend_shared_navigation_design(tmp_path) -> None:
    client = _client(PositionCache(tmp_path / "positions.sqlite3"))

    for route in ("/", "/search?q=not-a-ship", "/ship/koningsdam"):
        response = client.get(route)
        assert response.status_code == 200
        assert 'class="site-header"' in response.text
        assert "← Fleet Tracker Home" in response.text
        assert "/static/css/main.css" in response.text


def test_embedded_ship_map_data_is_valid_json(tmp_path) -> None:
    cache = PositionCache(tmp_path / "positions.sqlite3")
    cache.update(_position(vessel_name="Koningsdam"))
    response = _client(cache).get("/")
    match = re.search(
        r'<script id="fleet-map-data" type="application/json">(.*?)</script>',
        response.text,
        re.DOTALL,
    )

    assert match is not None
    ships = json.loads(match.group(1))
    assert isinstance(ships, list)
    assert ships[0]["name"] == "Koningsdam"
    assert ships[0]["latitude"] == 52.0


def test_leaflet_assets_load_before_dashboard_initialization(tmp_path) -> None:
    response = _client(PositionCache(tmp_path / "positions.sqlite3")).get("/")

    leaflet_css = response.text.index("leaflet@1.9.4/dist/leaflet.css")
    leaflet_js = response.text.index("leaflet@1.9.4/dist/leaflet.js")
    dashboard_js = response.text.index("/static/dashboard.js")

    assert leaflet_css < leaflet_js < dashboard_js
    leaflet_imports = response.text[leaflet_css - 100 : dashboard_js]
    assert "integrity=" not in leaflet_imports
    assert "crossorigin=" not in leaflet_imports
    assert "/static/dashboard.js?v=0.1.0" in response.text

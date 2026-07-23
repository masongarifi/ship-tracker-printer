from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Callable, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import __version__
from .cache import PositionCache
from .config import ConfigurationError
from .config import load_fleet
from .dashboard import (
    build_dashboard,
    build_ship_detail,
    exact_vessel_match,
    search_vessels,
    vessel_for_slug,
    vessel_slug,
)
from .reporting import render_cached_report

REFRESH_SECONDS = 30
PACKAGE_ROOT = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=PACKAGE_ROOT / "templates")


def _static_asset_version() -> str:
    digest = sha256()
    for path in sorted((PACKAGE_ROOT / "static").rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(PACKAGE_ROOT).as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


TEMPLATES.env.globals["asset_version"] = _static_asset_version()


def create_app(
    cache: Optional[PositionCache] = None,
    now_factory: Optional[Callable[[], datetime]] = None,
) -> FastAPI:
    active_cache = cache or PositionCache()
    clock = now_factory or (lambda: datetime.now(timezone.utc))
    app = FastAPI(
        title="Fleet Operations Brief",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.mount(
        "/static",
        StaticFiles(directory=PACKAGE_ROOT / "static"),
        name="static",
    )

    def profile_page(request: Request, fleet_profile: str, heading: str):
        refreshed_at = _aware_utc(clock())
        report = _render_profile(active_cache, refreshed_at, fleet_profile)
        navigation = (
            (
                "HAL + Seabourn",
                str(app.url_path_for("combined_fleet_page")),
            ),
            ("Celebrity", str(app.url_path_for("celebrity_page"))),
            (
                "Royal Caribbean",
                str(app.url_path_for("royal_caribbean_page")),
            ),
            ("Carnival", str(app.url_path_for("carnival_page"))),
            ("Princess", str(app.url_path_for("princess_page"))),
            ("Cunard", str(app.url_path_for("cunard_page"))),
            ("P&O Cruises", str(app.url_path_for("p_and_o_page"))),
            ("Costa", str(app.url_path_for("costa_page"))),
            ("AIDA", str(app.url_path_for("aida_page"))),
            ("All Fleets", str(app.url_path_for("all_fleets_page"))),
        )
        return TEMPLATES.TemplateResponse(
            request=request,
            name="fleet.html",
            context={
                "report": report,
                "refreshed_at": refreshed_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
                "heading": heading,
                "navigation": navigation,
                "page_title": f"Fleet Operations Brief — {heading}",
                "page_subtitle": heading,
                "version": __version__,
                "refresh_seconds": REFRESH_SECONDS,
            },
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/", response_class=HTMLResponse)
    def dashboard_page(request: Request):
        generated_at = _aware_utc(clock())
        dashboard = build_dashboard(
            load_fleet(profile="all"),
            active_cache.load(),
            generated_at,
        )
        return TEMPLATES.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={
                "dashboard": dashboard,
                "version": __version__,
                "page_title": "Live Cruise Fleet Dashboard",
                "page_subtitle": "Live Cruise Fleet Dashboard",
            },
            headers={"Cache-Control": "no-store"},
        )

    @app.get(
        "/hal-seabourn",
        response_class=HTMLResponse,
        name="combined_fleet_page",
    )
    def combined_fleet_page(request: Request):
        return profile_page(request, "main", "HAL + Seabourn")

    @app.get("/hal", response_class=HTMLResponse)
    def hal_page(request: Request):
        return profile_page(request, "hal", "Holland America")

    @app.get("/seabourn", response_class=HTMLResponse)
    def seabourn_page(request: Request):
        return profile_page(request, "seabourn", "Seabourn")

    @app.get("/celebrity", response_class=HTMLResponse)
    def celebrity_page(request: Request):
        return profile_page(request, "celebrity", "Celebrity Cruises")

    @app.get("/profile/celebrity", response_class=HTMLResponse)
    def celebrity_profile_page(request: Request):
        return profile_page(request, "celebrity", "Celebrity Cruises")

    @app.get("/royal-caribbean", response_class=HTMLResponse)
    def royal_caribbean_page(request: Request):
        return profile_page(
            request, "royal-caribbean", "Royal Caribbean International"
        )

    @app.get("/profile/royal-caribbean", response_class=HTMLResponse)
    def royal_caribbean_profile_page(request: Request):
        return profile_page(
            request, "royal-caribbean", "Royal Caribbean International"
        )

    @app.get("/carnival", response_class=HTMLResponse)
    def carnival_page(request: Request):
        return profile_page(request, "carnival", "Carnival Cruise Line")

    @app.get("/profile/carnival", response_class=HTMLResponse)
    def carnival_profile_page(request: Request):
        return profile_page(request, "carnival", "Carnival Cruise Line")

    @app.get("/princess", response_class=HTMLResponse)
    def princess_page(request: Request):
        return profile_page(request, "princess", "Princess Cruises")

    @app.get("/profile/princess", response_class=HTMLResponse)
    def princess_profile_page(request: Request):
        return profile_page(request, "princess", "Princess Cruises")

    @app.get("/cunard", response_class=HTMLResponse)
    def cunard_page(request: Request):
        return profile_page(request, "cunard", "Cunard")

    @app.get("/profile/cunard", response_class=HTMLResponse)
    def cunard_profile_page(request: Request):
        return profile_page(request, "cunard", "Cunard")

    @app.get("/p-and-o", response_class=HTMLResponse)
    def p_and_o_page(request: Request):
        return profile_page(request, "p-and-o", "P&O Cruises")

    @app.get("/profile/p-and-o", response_class=HTMLResponse)
    def p_and_o_profile_page(request: Request):
        return profile_page(request, "p-and-o", "P&O Cruises")

    @app.get("/costa", response_class=HTMLResponse)
    def costa_page(request: Request):
        return profile_page(request, "costa", "Costa Cruises")

    @app.get("/profile/costa", response_class=HTMLResponse)
    def costa_profile_page(request: Request):
        return profile_page(request, "costa", "Costa Cruises")

    @app.get("/aida", response_class=HTMLResponse)
    def aida_page(request: Request):
        return profile_page(request, "aida", "AIDA Cruises")

    @app.get("/profile/aida", response_class=HTMLResponse)
    def aida_profile_page(request: Request):
        return profile_page(request, "aida", "AIDA Cruises")

    @app.get("/all", response_class=HTMLResponse)
    def all_fleets_page(request: Request):
        return profile_page(request, "all", "All Fleets")

    @app.get("/search", response_class=HTMLResponse)
    def search_page(request: Request, q: str = ""):
        fleet = load_fleet(profile="all")
        results = search_vessels(fleet, q)
        exact = exact_vessel_match(results, q)
        if exact is not None:
            return RedirectResponse(f"/ship/{vessel_slug(exact.name)}", status_code=303)
        return TEMPLATES.TemplateResponse(
            request=request,
            name="search.html",
            context={
                "query": q,
                "results": [
                    {
                        "name": vessel.name,
                        "fleet": vessel.cruise_line,
                        "imo": vessel.imo or "Unavailable",
                        "mmsi": vessel.mmsi or "Unavailable",
                        "slug": vessel_slug(vessel.name),
                    }
                    for vessel in results
                ],
                "version": __version__,
                "page_title": "Ship Search",
                "page_subtitle": "Ship Search",
            },
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/ship/{slug}", response_class=HTMLResponse)
    def ship_page(request: Request, slug: str):
        fleet = load_fleet(profile="all")
        vessel = vessel_for_slug(fleet, slug)
        if vessel is None:
            raise HTTPException(status_code=404, detail="Ship not found")
        position = active_cache.load().get(vessel.name.casefold())
        ship = build_ship_detail(vessel, position, _aware_utc(clock()))
        return TEMPLATES.TemplateResponse(
            request=request,
            name="ship.html",
            context={
                "ship": ship,
                "version": __version__,
                "page_title": vessel.name,
                "page_subtitle": "Vessel Details",
            },
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/report", response_class=PlainTextResponse)
    def report_text(fleet: str = "main"):
        return PlainTextResponse(
            _render_profile(active_cache, _aware_utc(clock()), fleet),
            media_type="text/plain",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/health")
    def health():
        now = _aware_utc(clock())
        positions = active_cache.load()
        newest = max(
            (position.position_timestamp for position in positions.values()),
            default=None,
        )
        newest_utc = _aware_utc(newest) if newest is not None else None
        age_seconds = (
            max(0, int((now - newest_utc).total_seconds()))
            if newest_utc is not None
            else None
        )
        return {
            "status": "ok",
            "cache_database_available": active_cache.path.exists(),
            "cached_vessels": len(positions),
            "newest_ais_update": newest_utc.isoformat() if newest_utc else None,
            "newest_ais_update_age_seconds": age_seconds,
        }

    return app


def _render_profile(
    cache: PositionCache,
    generated_at: datetime,
    fleet_profile: str,
) -> str:
    try:
        return render_cached_report(
            cache,
            generated_at=generated_at,
            fleet_profile=fleet_profile,
        )
    except ConfigurationError as exc:
        raise HTTPException(status_code=404, detail="Unknown fleet profile") from exc


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

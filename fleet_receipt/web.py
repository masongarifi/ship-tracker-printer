import html
from datetime import datetime, timezone
from typing import Callable, Optional

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, PlainTextResponse

from .cache import PositionCache
from .reporting import render_cached_report

REFRESH_SECONDS = 30


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

    @app.get("/", response_class=HTMLResponse)
    def receipt_page():
        refreshed_at = _aware_utc(clock())
        report = render_cached_report(active_cache, generated_at=refreshed_at)
        return HTMLResponse(
            _receipt_html(report, refreshed_at),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/report", response_class=PlainTextResponse)
    def report_text():
        return PlainTextResponse(
            render_cached_report(active_cache, generated_at=_aware_utc(clock())),
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


def _receipt_html(report: str, refreshed_at: datetime) -> str:
    safe_report = html.escape(report)
    refreshed = html.escape(refreshed_at.strftime("%Y-%m-%d %H:%M:%S UTC"))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="{REFRESH_SECONDS}">
  <title>Fleet Operations Brief</title>
  <style>
    :root {{
      color-scheme: light;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas,
                   "Liberation Mono", "Courier New", monospace;
      background: #eeeae1;
      color: #181815;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: clamp(0.75rem, 3vw, 2rem);
      min-height: 100vh;
      background: #eeeae1;
    }}
    main {{
      width: min(100%, 48rem);
      margin: 0 auto;
    }}
    h1 {{
      margin: 0 0 0.35rem;
      font: 700 clamp(1rem, 4vw, 1.25rem)/1.2 system-ui, sans-serif;
      letter-spacing: 0.02em;
    }}
    .refreshed {{
      margin: 0 0 0.8rem;
      color: #605e56;
      font: 500 0.78rem/1.4 system-ui, sans-serif;
    }}
    pre {{
      margin: 0;
      padding: clamp(0.85rem, 3vw, 1.4rem);
      border: 1px solid #d5d0c4;
      border-radius: 0.35rem;
      background: #fffef9;
      color: #181815;
      box-shadow: 0 0.3rem 1.2rem rgb(45 40 30 / 8%);
      font: 500 clamp(0.72rem, 2.6vw, 0.94rem)/1.36 ui-monospace,
            SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono",
            "Courier New", monospace;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      tab-size: 2;
    }}
    @media (max-width: 28rem) {{
      body {{ padding: 0.5rem; }}
      pre {{ padding: 0.7rem; border-radius: 0.2rem; }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>Fleet Operations Brief</h1>
    <p class="refreshed">Page refreshed: {refreshed} &middot; Auto-refreshes every 30 seconds</p>
    <pre aria-label="Fleet operations receipt">{safe_report}</pre>
  </main>
</body>
</html>
"""


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

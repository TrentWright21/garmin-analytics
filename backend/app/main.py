"""FastAPI application entrypoint.

Boots the app with validated config, structured logging, a health probe, the
API routers, and a background scheduler (daily Garmin sync, nightly DB backup,
optional morning message). In production it is fail-closed: it refuses to start
without an app-login password, gates the interactive docs, and requires a bearer
token on every /api/* call (except login and the separately-guarded watch feed).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app import auth
from app.api.routes.auth import router as auth_router
from app.api.routes.briefing import router as briefing_router
from app.api.routes.chat import router as chat_router
from app.api.routes.coach import router as coach_router
from app.api.routes.core import router as api_router
from app.api.routes.performance import router as performance_router
from app.config import REPO_ROOT, get_app_config, get_settings
from app.logging import configure_logging, get_logger
from app.notify import is_configured as notify_configured

FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"

# /api/* paths that must stay reachable without a session token: the login
# exchange, the "is a login required?" probe, and the watch feed (which carries
# its own GA_WATCH_TOKEN guard because a watch can't do the browser login flow).
_AUTH_EXEMPT_PREFIXES = ("/api/login", "/api/auth/status", "/api/watch/")


def _needs_auth(path: str) -> bool:
    return path.startswith("/api/") and not path.startswith(_AUTH_EXEMPT_PREFIXES)


async def _auth_dispatch(request: Request, call_next: RequestResponseEndpoint) -> Response:
    """Reject protected /api/* requests that lack a valid session token.

    No-op when auth is disabled (no GA_APP_PASSWORD) so local dev and the test
    suite run without a login. Reads settings per-request so a token set after
    import is honored.
    """
    settings = get_settings()
    if (
        request.method == "OPTIONS"
        or not auth.auth_enabled(settings)
        or not _needs_auth(request.url.path)
    ):
        return await call_next(request)
    token = auth.bearer_from_header(request.headers.get("authorization"))
    if not auth.verify_token(settings, token):
        return JSONResponse({"detail": "Authentication required."}, status_code=401)
    return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    log = get_logger(__name__)
    settings = get_settings()
    cfg = get_app_config()

    # Fail-closed: never run publicly without a login password.
    if settings.environment == "prod" and not auth.auth_enabled(settings):
        raise RuntimeError(
            "GA_APP_PASSWORD is required when GA_ENVIRONMENT=prod. Set it in .env so "
            "the API isn't world-readable, then restart. (See DEPLOY.md.)"
        )

    log.info(
        "app.started",
        environment=settings.environment,
        timezone=cfg.timezone,
        sync_time=f"{cfg.sync.hour:02d}:{cfg.sync.minute:02d}",
        auth_enabled=auth.auth_enabled(settings),
        notify_enabled=cfg.notify.enabled and notify_configured(settings),
    )
    scheduler = BackgroundScheduler(timezone=cfg.timezone)

    def daily_sync() -> None:
        from app.collectors.garmin_connect import GarminConnectCollector
        from app.collectors.sync import build_sync_engine

        try:
            build_sync_engine(GarminConnectCollector(get_settings())).sync_recent(days=2)
        except Exception:
            log.exception("scheduled_sync.failed")

    def nightly_backup() -> None:
        from app.db.backup import backup_database

        try:
            backup_database()
        except Exception:
            log.exception("scheduled_backup.failed")

    def morning_message() -> None:
        from app.notify.message import send_morning_briefing

        try:
            send_morning_briefing(get_settings(), get_app_config())
        except Exception:
            log.exception("morning_message.failed")

    scheduler.add_job(daily_sync, "cron", hour=cfg.sync.hour, minute=cfg.sync.minute)
    scheduler.add_job(nightly_backup, "cron", hour=3, minute=15)
    if cfg.notify.enabled:
        scheduler.add_job(morning_message, "cron", hour=cfg.notify.hour, minute=cfg.notify.minute)
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)
    log.info("app.stopped")


_settings = get_settings()
_cfg = get_app_config()
_is_prod = _settings.environment == "prod"

app = FastAPI(
    title="Waypoint",
    version="0.1.0",
    lifespan=lifespan,
    # Interactive docs expose the full API surface — off in prod.
    docs_url=None if _is_prod else "/docs",
    redoc_url=None if _is_prod else "/redoc",
    openapi_url=None if _is_prod else "/openapi.json",
)

# Middleware nests in reverse add-order (last added = outermost). Target request
# order: TrustedHost -> CORS -> Auth -> routes. So add Auth first, then CORS,
# then TrustedHost.
app.add_middleware(BaseHTTPMiddleware, dispatch=_auth_dispatch)

# CORS so a cross-origin browser (the Vite dev server) can call the API. The dev
# origin is always allowed in dev; prod adds only what config lists (empty by
# default, since the built dashboard is served same-origin).
_cors_origins = (
    ["http://localhost:5173", "http://127.0.0.1:5173", *_cfg.cors_origins]
    if not _is_prod
    else list(_cfg.cors_origins)
)
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Optional host allowlist. Empty (default) allows any host — correct for
# Tailscale, where the tailnet hostname varies. Set config.allowed_hosts to lock.
if _cfg.allowed_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_cfg.allowed_hosts)

app.include_router(auth_router)
app.include_router(api_router)
app.include_router(performance_router)
app.include_router(briefing_router)
app.include_router(coach_router)
app.include_router(chat_router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe for Docker and uptime checks (always unauthenticated)."""
    return {"status": "ok", "environment": get_settings().environment}


# -- static frontend (production build) --------------------------------------
# When `frontend/dist` exists (after `npm run build`), serve the React dashboard
# from this same server so `.\start.ps1` puts everything on localhost:3000. The
# catch-all falls back to index.html for client-side routes (/sleep, /pace, ...).
if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")
    _DIST_ROOT = FRONTEND_DIST.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        # Resolve and CONTAIN: a request path may carry `..` (browsers normalize
        # it, but percent-encoded `%2e%2e`/`%2f` reach us decoded by uvicorn).
        # pathlib's `/` does NOT collapse `..`, and `.is_file()` resolves it at
        # the OS level, so `frontend/dist/../../.env` would otherwise be served.
        # Reject anything that resolves outside the built dashboard directory.
        candidate = (_DIST_ROOT / full_path).resolve()
        inside = candidate == _DIST_ROOT or _DIST_ROOT in candidate.parents
        if full_path and inside and candidate.is_file() and candidate.name != "index.html":
            # Hashed assets are content-addressed, so they're safe to cache.
            return FileResponse(candidate)
        # index.html (and every client-side route) must always revalidate, or the
        # browser keeps serving a stale page that points at old asset hashes after
        # a rebuild — the "I updated but the browser shows the old UI" trap.
        return FileResponse(FRONTEND_DIST / "index.html", headers={"Cache-Control": "no-cache"})

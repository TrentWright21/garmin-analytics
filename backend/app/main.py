"""FastAPI application entrypoint.

M1 scope: boot the app with validated config, structured logging, and a
health endpoint. The scheduler and API routers plug into the lifespan hook
and `include_router` calls in later milestones.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes.coach import router as coach_router
from app.api.routes.core import router as api_router
from app.config import REPO_ROOT, get_app_config, get_settings
from app.logging import configure_logging, get_logger

FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    log = get_logger(__name__)
    settings = get_settings()
    cfg = get_app_config()
    log.info(
        "app.started",
        environment=settings.environment,
        timezone=cfg.timezone,
        sync_time=f"{cfg.sync.hour:02d}:{cfg.sync.minute:02d}",
    )
    scheduler = BackgroundScheduler(timezone=cfg.timezone)

    def daily_sync() -> None:
        from app.collectors.garmin_connect import GarminConnectCollector
        from app.collectors.sync import SyncEngine

        try:
            SyncEngine(GarminConnectCollector(get_settings())).sync_recent(days=2)
        except Exception:
            log.exception("scheduled_sync.failed")

    scheduler.add_job(daily_sync, "cron", hour=cfg.sync.hour, minute=cfg.sync.minute)
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)
    log.info("app.stopped")


app = FastAPI(
    title="Garmin Analytics",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS so the Vite dev server (localhost:5173) can call the API during development.
# In production the built frontend is served from this same origin (below), so CORS
# is not exercised there.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(coach_router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe for Docker and uptime checks."""
    return {"status": "ok", "environment": get_settings().environment}


# -- static frontend (production build) --------------------------------------
# When `frontend/dist` exists (after `npm run build`), serve the React dashboard
# from this same server so `.\start.ps1` puts everything on localhost:3000. The
# catch-all falls back to index.html for client-side routes (/sleep, /pace, ...).
if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")

"""Auth API: login status and password -> session-token exchange.

Both endpoints are intentionally unauthenticated (they are how you *get* a
token, and how the frontend decides whether to show a login screen). Login is
rate-limited to blunt brute-force attempts. Everything else under /api requires
the token this issues; see app.auth and the AuthMiddleware in main.py.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import auth
from app.config import get_settings
from app.ratelimit import RateLimiter, rate_limiter

router = APIRouter(prefix="/api")

# 10 login attempts / minute is plenty for a human and slow for a brute-forcer.
_login_limiter = RateLimiter(max_calls=10, window_s=60.0)


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=512)


@router.get("/auth/status")
def auth_status() -> dict[str, bool]:
    """Whether the app requires a login (drives the frontend login gate)."""
    return {"auth_required": auth.auth_enabled(get_settings())}


@router.post("/login", dependencies=[Depends(rate_limiter(_login_limiter))])
def login(req: LoginRequest) -> dict[str, str]:
    """Exchange the shared password for a session token."""
    settings = get_settings()
    if not auth.auth_enabled(settings):
        # Auth is off: no password to check. Hand back a token anyway so the
        # frontend flow is uniform, but it isn't required for any request.
        return {"token": ""}
    if not auth.check_password(settings, req.password):
        raise HTTPException(status_code=401, detail="Incorrect password.")
    return {"token": auth.mint_token(settings)}

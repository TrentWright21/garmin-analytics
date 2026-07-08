"""App authentication: one shared password -> short-lived signed session tokens.

Single-user by design. ``POST /api/login`` checks the configured password
(``GA_APP_PASSWORD``) in constant time and, on success, mints an HMAC-signed
token carrying an expiry. Every protected request presents that token as
``Authorization: Bearer <token>``; the middleware verifies the signature and
expiry (also constant time). No sessions table and no second secret: the signing
key is derived from the password, so changing the password invalidates every
outstanding token.

Auth is OFF when ``GA_APP_PASSWORD`` is unset (safe only on a trusted localhost).
In ``prod`` the app refuses to start without it (fail-closed) — see main.py.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from app.config import Settings

# 30 days: a personal tool you reach from your own phone shouldn't demand a
# fresh login every session. Rotating GA_APP_PASSWORD revokes all tokens sooner.
TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60


def auth_enabled(settings: Settings) -> bool:
    """True when a login password is configured (auth enforced)."""
    return settings.app_password is not None


def _signing_key(settings: Settings) -> bytes:
    """HMAC key derived from the app password. None-safe caller required."""
    assert settings.app_password is not None  # callers guard with auth_enabled()
    return hashlib.sha256(
        b"waypoint.session.v1:" + settings.app_password.get_secret_value().encode()
    ).digest()


def check_password(settings: Settings, password: str) -> bool:
    """Constant-time comparison of a submitted password against the configured one."""
    if settings.app_password is None:
        return False
    return hmac.compare_digest(password, settings.app_password.get_secret_value())


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def mint_token(settings: Settings, *, now: float | None = None) -> str:
    """Create a signed session token valid for TOKEN_TTL_SECONDS."""
    exp = int((now if now is not None else time.time()) + TOKEN_TTL_SECONDS)
    body = _b64e(json.dumps({"exp": exp}, separators=(",", ":")).encode())
    sig = _b64e(hmac.new(_signing_key(settings), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_token(settings: Settings, token: str | None, *, now: float | None = None) -> bool:
    """True if ``token`` is a valid, unexpired, correctly-signed session token."""
    if settings.app_password is None or not token or token.count(".") != 1:
        return False
    body, sig = token.split(".", 1)
    expected = _b64e(hmac.new(_signing_key(settings), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        payload: dict[str, Any] = json.loads(_b64d(body))
    except (ValueError, TypeError):
        return False
    exp = payload.get("exp")
    current = now if now is not None else time.time()
    return isinstance(exp, int) and current < exp


def bearer_from_header(authorization: str | None) -> str | None:
    """Extract the token from an ``Authorization: Bearer <token>`` header."""
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value:
        return None
    return value.strip()

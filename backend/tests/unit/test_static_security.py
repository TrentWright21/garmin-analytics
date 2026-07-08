"""Regression tests for the SPA static-file handler.

The catch-all that serves the built dashboard must never serve a file outside
`frontend/dist`. Percent-encoded dot-segments (`%2e%2e`, `%2f`) survive
client-side normalization and are decoded by the server, so a naive
`FRONTEND_DIST / full_path` would leak `.env`, the SQLite DB, or source.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from app.config import REPO_ROOT
from app.main import FRONTEND_DIST


def _client() -> TestClient:
    import app.main

    importlib.reload(app.main)
    return TestClient(app.main.app)


@pytest.mark.skipif(not FRONTEND_DIST.is_dir(), reason="dashboard not built (no frontend/dist)")
def test_spa_rejects_path_traversal() -> None:
    """Encoded `..` traversal must not return the real .env, only the SPA shell."""
    env_path = REPO_ROOT / ".env"
    env_bytes = env_path.read_bytes() if env_path.exists() else b""

    client = _client()
    for attack in (
        "/%2e%2e/%2e%2e/.env",
        "/..%2f..%2f.env",
        "/assets/..%2f..%2f..%2f.env",
        "/%2e%2e%2f%2e%2e%2fbackend%2fapp%2fconfig.py",
    ):
        resp = client.get(attack)
        # Either a clean 404, or the SPA fallback — never the traversed file.
        if resp.status_code == 200:
            assert b"GA_GARMIN_PASSWORD" not in resp.content
            if env_bytes:
                assert resp.content != env_bytes

"""M1 foundation tests: config validation, yaml loading, health endpoint."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import AppConfig, Settings
from app.main import app


class TestAppConfig:
    def test_defaults_when_yaml_missing(self, tmp_path: Path) -> None:
        cfg = AppConfig.from_yaml(tmp_path / "nope.yaml")
        assert cfg.log_level == "INFO"
        assert cfg.sync.hour == 6

    def test_loads_yaml(self, tmp_path: Path) -> None:
        f = tmp_path / "config.yaml"
        f.write_text("log_level: DEBUG\nsync:\n  hour: 4\n  backfill_days: 365\n")
        cfg = AppConfig.from_yaml(f)
        assert cfg.log_level == "DEBUG"
        assert cfg.sync.hour == 4
        assert cfg.sync.backfill_days == 365

    def test_invalid_values_fail_loudly(self, tmp_path: Path) -> None:
        f = tmp_path / "config.yaml"
        f.write_text("sync:\n  hour: 99\n")
        with pytest.raises(ValidationError):
            AppConfig.from_yaml(f)


class TestSettings:
    def test_secrets_never_leak_in_repr(self) -> None:
        s = Settings(garmin_email="a@b.com", garmin_password="hunter2", _env_file=None)
        assert "hunter2" not in repr(s)
        assert s.garmin_password is not None
        assert s.garmin_password.get_secret_value() == "hunter2"

    def test_env_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GA_ENVIRONMENT", "prod")
        s = Settings(_env_file=None)
        assert s.environment == "prod"


class TestHealthEndpoint:
    def test_health_ok(self) -> None:
        with TestClient(app) as client:
            resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

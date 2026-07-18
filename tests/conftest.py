"""Shared pytest fixtures."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture()
def app_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "auth.db"
    monkeypatch.setenv("ADMIN_API_KEY", "test-admin-key")
    monkeypatch.setenv("API_KEY", "legacy-shared-key")
    monkeypatch.setenv("ENABLE_LEGACY_API_KEY", "true")
    monkeypatch.setenv("AUTH_DB_PATH", str(db_path))
    monkeypatch.setenv("DEFAULT_RPM_LIMIT", "60")
    monkeypatch.setenv("DEFAULT_MONTHLY_TOKEN_QUOTA", "2000000")
    monkeypatch.setenv("AWS_REGION", "us-west-2")

    for name in list(sys.modules):
        if name == "api" or name.startswith("api."):
            del sys.modules[name]

    import api.db as db_mod
    import api.setting as setting_mod

    importlib.reload(setting_mod)
    db_mod.auth_db = db_mod.AuthDatabase(str(db_path))

    import api.auth as auth_mod

    importlib.reload(auth_mod)

    import api.app as app_mod

    importlib.reload(app_mod)

    with TestClient(app_mod.app) as client:
        yield client, db_mod.auth_db

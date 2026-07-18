"""IP ban + auto-ban after failed admin logins."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_manual_ban_blocks_requests(app_client):
    client, db = app_client
    from api.security import mark_ip_banned, mark_ip_unbanned, refresh_banned_ips_cache

    refresh_banned_ips_cache()
    rec = db.ban_ip("203.0.113.50", reason="test spam", source="manual")
    assert rec.ip == "203.0.113.50"
    mark_ip_banned(rec.ip)

    blocked = client.get("/api/v1/models", headers={"X-Forwarded-For": "203.0.113.50"})
    assert blocked.status_code == 403
    assert "banned" in blocked.json()["detail"].lower()

    db.unban_ip("203.0.113.50")
    mark_ip_unbanned("203.0.113.50")
    # Without API key this is 401, not 403 banned
    again = client.get("/api/v1/models", headers={"X-Forwarded-For": "203.0.113.50"})
    assert again.status_code != 403 or "banned" not in (again.json().get("detail") or "").lower()


def test_auto_ban_after_10_failed_logins(app_client, monkeypatch):
    import api.setting as setting_mod
    from api.security import admin_login_limiter, is_ip_banned, refresh_banned_ips_cache

    salt = "ban-salt"
    password = "correct-horse"
    digest = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    monkeypatch.setenv("ADMIN_USERNAME", "mrdev")
    monkeypatch.setenv("ADMIN_PASSWORD_SALT", salt)
    monkeypatch.setenv("ADMIN_PASSWORD_SHA256", digest)
    setting_mod.ADMIN_USERNAME = "mrdev"
    setting_mod.ADMIN_PASSWORD = None
    setting_mod.ADMIN_PASSWORD_SALT = salt
    setting_mod.ADMIN_PASSWORD_SHA256 = digest
    setting_mod.ADMIN_LOGIN_MAX_FAILURES = 10
    admin_login_limiter._failures.clear()
    admin_login_limiter._locked_until.clear()
    refresh_banned_ips_cache()

    client, db = app_client
    ip = "198.51.100.77"
    headers = {"X-Forwarded-For": ip}

    for i in range(9):
        r = client.post(
            "/admin/login",
            headers=headers,
            json={"username": "mrdev", "password": "wrong"},
        )
        assert r.status_code == 401, i

    tenth = client.post(
        "/admin/login",
        headers=headers,
        json={"username": "mrdev", "password": "wrong"},
    )
    assert tenth.status_code == 403
    assert is_ip_banned(ip)
    assert db.is_ip_banned(ip)

    after = client.get("/admin/models", headers=headers)
    assert after.status_code == 403

"""Tests for multi-key auth, quotas, admin API, and usage accounting."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _admin_headers():
    return {"Authorization": "Bearer test-admin-key"}


def test_health(app_client):
    client, _ = app_client
    assert client.get("/health").json() == {"status": "OK"}


def test_create_list_revoke_key(app_client):
    client, db = app_client
    created = client.post(
        "/admin/keys",
        headers=_admin_headers(),
        json={"name": "alice", "rpm_limit": 5, "monthly_token_quota": 1000},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "alice"
    assert body["api_key"].startswith("bag_")
    api_key = body["api_key"]
    key_id = body["key_id"]

    listed = client.get("/admin/keys", headers=_admin_headers())
    assert listed.status_code == 200
    assert any(k["key_id"] == key_id for k in listed.json())

    # Valid key can hit models endpoint (mock Bedrock list)
    with patch("api.routers.model.chat_model.list_models", return_value=["us.anthropic.claude-opus-4-6-v1"]):
        ok = client.get("/api/v1/models", headers={"Authorization": f"Bearer {api_key}"})
    assert ok.status_code == 200
    assert ok.json()["data"][0]["id"] == "us.anthropic.claude-opus-4-6-v1"

    revoked = client.delete(f"/admin/keys/{key_id}", headers=_admin_headers())
    assert revoked.status_code == 200
    assert revoked.json()["revoked"] is True

    denied = client.get("/api/v1/models", headers={"Authorization": f"Bearer {api_key}"})
    assert denied.status_code == 401


def test_invalid_key(app_client):
    client, _ = app_client
    resp = client.get("/api/v1/models", headers={"Authorization": "Bearer bag_deadbeef_notreal"})
    assert resp.status_code == 401


def test_hard_delete_key_keeps_usage_logs(app_client):
    from api.schema import ChatResponse, ChatResponseMessage, Choice, Usage

    client, db = app_client
    created = client.post(
        "/admin/keys",
        headers=_admin_headers(),
        json={"name": "temp-del", "rpm_limit": 10, "monthly_token_quota": 1000},
    ).json()
    key_id = created["key_id"]
    api_key = created["api_key"]

    fake_response = ChatResponse(
        id="chatcmpl-del",
        model="us.anthropic.claude-opus-4-6-v1",
        choices=[
            Choice(
                index=0,
                finish_reason="stop",
                message=ChatResponseMessage(role="assistant", content="ok"),
            )
        ],
        usage=Usage(prompt_tokens=12, completion_tokens=3, total_tokens=15),
    )
    with patch("api.routers.chat.BedrockModel") as model_cls:
        instance = model_cls.return_value
        instance.validate = MagicMock()
        instance.chat = AsyncMock(return_value=fake_response)
        assert (
            client.post(
                "/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "us.anthropic.claude-opus-4-6-v1",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            ).status_code
            == 200
        )

    assert db.count_usage_logs(key_id) == 1
    deleted = client.delete(f"/admin/keys/{key_id}/hard", headers=_admin_headers())
    assert deleted.status_code == 200
    assert db.get_key(key_id) is None
    assert db.count_usage_logs(key_id) == 1

    summary = client.get("/admin/usage/summary?period=day", headers=_admin_headers())
    assert summary.status_code == 200
    body = summary.json()
    assert body["total_tokens"] >= 15
    assert any(k["key_id"] == key_id and k["key_deleted"] for k in body["by_key"])

    cdks = client.post(
        "/admin/cdks",
        headers=_admin_headers(),
        json={"label": "temp", "count": 1},
    ).json()
    code = cdks[0]["code"]
    gone = client.delete(f"/admin/cdks/{code}/hard", headers=_admin_headers())
    assert gone.status_code == 200
    assert all(c.code != code.upper() for c in db.list_cdks())


def test_api_requires_bearer_key(app_client):
    client, _ = app_client
    no_auth = client.get("/api/v1/models")
    assert no_auth.status_code in (401, 403)
    chat = client.post(
        "/api/v1/chat/completions",
        json={"model": "x", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert chat.status_code in (401, 403)


def test_legacy_key_still_works(app_client):
    client, _ = app_client
    with patch("api.routers.model.chat_model.list_models", return_value=["m1"]):
        resp = client.get("/api/v1/models", headers={"Authorization": "Bearer legacy-shared-key"})
    assert resp.status_code == 200


def test_rpm_limit_returns_429(app_client):
    client, _ = app_client
    created = client.post(
        "/admin/keys",
        headers=_admin_headers(),
        json={"name": "rpm", "rpm_limit": 2, "monthly_token_quota": 100000},
    ).json()
    api_key = created["api_key"]
    headers = {"Authorization": f"Bearer {api_key}"}

    with patch("api.routers.model.chat_model.list_models", return_value=["m1"]):
        assert client.get("/api/v1/models", headers=headers).status_code == 200
        assert client.get("/api/v1/models", headers=headers).status_code == 200
        limited = client.get("/api/v1/models", headers=headers)
    assert limited.status_code == 429
    assert "Rate limit" in limited.json()["detail"]


def test_monthly_quota_returns_429(app_client):
    client, db = app_client
    created = client.post(
        "/admin/keys",
        headers=_admin_headers(),
        json={"name": "quota", "rpm_limit": 60, "monthly_token_quota": 10},
    ).json()
    key_id = created["key_id"]
    api_key = created["api_key"]
    db.record_usage(key_id, prompt_tokens=8, completion_tokens=3)

    with patch("api.routers.model.chat_model.list_models", return_value=["m1"]):
        resp = client.get("/api/v1/models", headers={"Authorization": f"Bearer {api_key}"})
    assert resp.status_code == 429
    assert "quota" in resp.json()["detail"].lower()


def test_chat_records_usage(app_client):
    from api.schema import ChatResponse, ChatResponseMessage, Choice, PromptTokensDetails, Usage

    client, db = app_client
    created = client.post(
        "/admin/keys",
        headers=_admin_headers(),
        json={"name": "chat", "rpm_limit": 60, "monthly_token_quota": 100000},
    ).json()
    api_key = created["api_key"]
    key_id = created["key_id"]

    fake_response = ChatResponse(
        id="chatcmpl-test",
        model="us.anthropic.claude-opus-4-6-v1",
        choices=[
            Choice(
                index=0,
                finish_reason="stop",
                message=ChatResponseMessage(role="assistant", content="hello"),
            )
        ],
        usage=Usage(
            prompt_tokens=11,
            completion_tokens=7,
            total_tokens=18,
            prompt_tokens_details=PromptTokensDetails(
                cached_tokens=5,
                cache_write_tokens=3,
            ),
        ),
    )

    with patch("api.routers.chat.BedrockModel") as model_cls:
        instance = model_cls.return_value
        instance.validate = MagicMock()
        instance.chat = AsyncMock(return_value=fake_response)
        resp = client.post(
            "/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "us.anthropic.claude-opus-4-6-v1",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    assert resp.status_code == 200
    record = db.get_key(key_id)
    assert record.prompt_tokens_month == 11
    assert record.completion_tokens_month == 7

    logs = client.get("/api/v1/usage/logs", headers={"Authorization": f"Bearer {api_key}"})
    assert logs.status_code == 200
    log = logs.json()["logs"][0]
    assert log["model"] == "us.anthropic.claude-opus-4-6-v1"
    assert log["prompt_tokens"] == 11
    assert log["completion_tokens"] == 7
    assert log["cache_read_tokens"] == 5
    assert log["cache_write_tokens"] == 3
    assert log["total_tokens"] == 18
    assert log["client_ip"]


def test_stream_records_usage(app_client):
    client, db = app_client
    created = client.post(
        "/admin/keys",
        headers=_admin_headers(),
        json={"name": "stream", "rpm_limit": 60, "monthly_token_quota": 100000},
    ).json()
    api_key = created["api_key"]
    key_id = created["key_id"]

    async def fake_stream(_req):
        usage_chunk = {
            "id": "chatcmpl-x",
            "object": "chat.completion.chunk",
            "choices": [],
            "usage": {"prompt_tokens": 5, "completion_tokens": 9, "total_tokens": 14},
        }
        yield f"data: {json.dumps(usage_chunk)}\n\n".encode()
        yield b"data: [DONE]\n\n"

    with patch("api.routers.chat.BedrockModel") as model_cls:
        instance = model_cls.return_value
        instance.validate = MagicMock()
        instance.chat_stream = fake_stream
        resp = client.post(
            "/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "us.anthropic.claude-opus-4-6-v1",
                "stream": True,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    assert resp.status_code == 200
    _ = resp.content
    record = db.get_key(key_id)
    assert record.prompt_tokens_month == 5
    assert record.completion_tokens_month == 9


def test_update_quota(app_client):
    client, _ = app_client
    created = client.post(
        "/admin/keys",
        headers=_admin_headers(),
        json={"name": "upd"},
    ).json()
    key_id = created["key_id"]
    updated = client.patch(
        f"/admin/keys/{key_id}",
        headers=_admin_headers(),
        json={"rpm_limit": 10, "monthly_token_quota": 500000},
    )
    assert updated.status_code == 200
    assert updated.json()["rpm_limit"] == 10
    assert updated.json()["monthly_token_quota"] == 500000


def test_admin_requires_key(app_client):
    client, _ = app_client
    resp = client.get("/admin/keys")
    assert resp.status_code in (401, 403)


def test_me_endpoint_and_web_index(app_client):
    client, _ = app_client
    created = client.post(
        "/admin/keys",
        headers=_admin_headers(),
        json={"name": "portal", "rpm_limit": 60, "monthly_token_quota": 1000},
    ).json()
    api_key = created["api_key"]
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {api_key}"})
    assert me.status_code == 200
    assert me.json()["name"] == "portal"
    assert me.json()["key_id"] == created["key_id"]

    index = client.get("/")
    assert index.status_code == 200
    assert b"MRDEV Gateway" in index.content

    css = client.get("/static/styles.css")
    assert css.status_code == 200
    js = client.get("/static/app.js")
    assert js.status_code == 200


def test_allowed_models_restriction(app_client):
    from api.schema import ChatResponse, ChatResponseMessage, Choice, Usage

    client, _ = app_client
    created = client.post(
        "/admin/keys",
        headers=_admin_headers(),
        json={
            "name": "restricted",
            "rpm_limit": 60,
            "monthly_token_quota": 100000,
            "allowed_models": ["us.anthropic.claude-opus-4-6-v1"],
        },
    ).json()
    api_key = created["api_key"]
    assert created["allowed_models"] == ["us.anthropic.claude-opus-4-6-v1"]

    fake_response = ChatResponse(
        id="chatcmpl-test",
        model="us.anthropic.claude-opus-4-6-v1",
        choices=[
            Choice(
                index=0,
                finish_reason="stop",
                message=ChatResponseMessage(role="assistant", content="ok"),
            )
        ],
        usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )

    with patch("api.routers.chat.BedrockModel") as model_cls:
        instance = model_cls.return_value
        instance.validate = MagicMock()
        instance.chat = AsyncMock(return_value=fake_response)
        allowed = client.post(
            "/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "us.anthropic.claude-opus-4-6-v1",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        blocked = client.post(
            "/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "us.anthropic.claude-opus-4-8",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    assert allowed.status_code == 200
    assert blocked.status_code == 403
    assert "not allowed" in blocked.json()["detail"].lower()


def test_admin_password_login_and_cdk_redeem(app_client, monkeypatch):
    import hashlib

    import api.setting as setting_mod
    from api.security import admin_login_limiter

    salt = "test-salt"
    password = "mrdevdeptraivodich"
    digest = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    monkeypatch.setenv("ADMIN_USERNAME", "mrdev")
    monkeypatch.setenv("ADMIN_PASSWORD_SALT", salt)
    monkeypatch.setenv("ADMIN_PASSWORD_SHA256", digest)
    setting_mod.ADMIN_USERNAME = "mrdev"
    setting_mod.ADMIN_PASSWORD = None
    setting_mod.ADMIN_PASSWORD_SALT = salt
    setting_mod.ADMIN_PASSWORD_SHA256 = digest
    admin_login_limiter._failures.clear()
    admin_login_limiter._locked_until.clear()

    client, db = app_client
    bad = client.post("/admin/login", json={"username": "mrdev", "password": "wrong"})
    assert bad.status_code == 401

    # TOTP 2FA: authenticator secret + rotating 6-digit code
    from api.security import totp_code

    secret = db.generate_admin_totp_secret()
    bad_otp = client.post(
        "/admin/login",
        json={"username": "mrdev", "password": password, "otp": "000000"},
    )
    assert bad_otp.status_code == 401

    login = client.post(
        "/admin/login",
        json={"username": "mrdev", "password": password, "otp": totp_code(secret)},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    logs = client.get("/admin/login-logs", headers=headers)
    assert logs.status_code == 200
    assert logs.json()["total"] >= 1

    cdks = client.post(
        "/admin/cdks",
        headers=headers,
        json={"label": "promo", "count": 1, "rpm_limit": 30, "monthly_token_quota": 5000},
    )
    assert cdks.status_code == 201
    code = cdks.json()[0]["code"]
    assert code.startswith("CDK-")

    redeemed = client.post("/api/v1/redeem", json={"cdk": code})
    assert redeemed.status_code == 200
    api_key = redeemed.json()["api_key"]
    assert api_key.startswith("bag_")

    again = client.post("/api/v1/redeem", json={"cdk": code})
    assert again.status_code == 400

    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {api_key}"})
    assert me.status_code == 200
    assert me.json()["rpm_limit"] == 30

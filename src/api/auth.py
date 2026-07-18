"""API key authentication with multi-key SQLite support and legacy fallback."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
from dataclasses import dataclass
from typing import Annotated

import boto3
from botocore.exceptions import ClientError
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.db import QuotaExceededError, RateLimitError, auth_db
from api.setting import ENABLE_LEGACY_API_KEY, LEGACY_KEY_ID

api_key_param = os.environ.get("API_KEY_PARAM_NAME")
api_key_secret_arn = os.environ.get("API_KEY_SECRET_ARN")
api_key_env = os.environ.get("API_KEY")

legacy_api_key: str | None = None
if api_key_param:
    # For backward compatibility.
    # Please now use secrets manager instead.
    ssm = boto3.client("ssm")
    legacy_api_key = ssm.get_parameter(Name=api_key_param, WithDecryption=True)["Parameter"]["Value"]
elif api_key_secret_arn:
    sm = boto3.client("secretsmanager")
    try:
        response = sm.get_secret_value(SecretId=api_key_secret_arn)
        if "SecretString" in response:
            secret = json.loads(response["SecretString"])
            legacy_api_key = secret["api_key"]
    except ClientError as exc:
        raise RuntimeError("Unable to retrieve API KEY, please ensure the secret ARN is correct") from exc
    except KeyError as exc:
        raise RuntimeError('Please ensure the secret contains a "api_key" field') from exc
elif api_key_env:
    legacy_api_key = api_key_env

# auto_error=False so Anthropic clients can auth via x-api-key without Authorization: Bearer.
security = HTTPBearer(auto_error=False)


@dataclass
class ApiKeyContext:
    key_id: str
    name: str
    is_legacy: bool = False


def _legacy_match(token: str) -> bool:
    return bool(ENABLE_LEGACY_API_KEY and legacy_api_key and token == legacy_api_key)


def _extract_api_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
) -> str | None:
    if credentials and credentials.credentials:
        return credentials.credentials.strip()
    x_api_key = request.headers.get("x-api-key") or request.headers.get("X-Api-Key")
    if x_api_key:
        return x_api_key.strip()
    auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


async def api_key_auth(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)] = None,
) -> ApiKeyContext:
    token = _extract_api_token(request, credentials)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API Key (Authorization: Bearer … or x-api-key)",
        )

    if _legacy_match(token):
        return ApiKeyContext(key_id=LEGACY_KEY_ID, name="legacy", is_legacy=True)

    # Never block the event loop on SQLite under chat load.
    record = await asyncio.to_thread(auth_db.authenticate, token)
    if not record:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key")

    try:
        await asyncio.to_thread(auth_db.check_and_consume_request, record.key_id)
    except RateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": "60"},
        ) from exc
    except QuotaExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    return ApiKeyContext(key_id=record.key_id, name=record.name, is_legacy=False)


async def admin_api_key_auth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)] = None,
) -> str:
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin credentials")
    token = credentials.credentials
    admin_key = os.environ.get("ADMIN_API_KEY")
    if admin_key and secrets.compare_digest(token, admin_key):
        return token
    if await asyncio.to_thread(auth_db.validate_admin_session, token):
        return token
    if not admin_key:
        # Allow password-session-only mode when ADMIN_API_KEY unset but sessions work
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin credentials")
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin credentials")


def ensure_auth_configured() -> None:
    """Fail fast if no admin login method and no multi-key DB path is usable."""
    has_admin = bool(os.environ.get("ADMIN_API_KEY"))
    has_password_hash = bool(os.environ.get("ADMIN_PASSWORD_SHA256"))
    has_password_plain = bool(os.environ.get("ADMIN_PASSWORD"))
    has_legacy = bool(ENABLE_LEGACY_API_KEY and legacy_api_key)
    if not has_admin and not has_password_hash and not has_password_plain and not has_legacy:
        raise RuntimeError(
            "Auth is not configured. Set ADMIN_PASSWORD_SHA256 (recommended) and/or ADMIN_API_KEY."
        )


# Validate at import so local/uvicorn startups fail clearly.
ensure_auth_configured()

__all__ = [
    "ApiKeyContext",
    "admin_api_key_auth",
    "api_key_auth",
    "ensure_auth_configured",
    "legacy_api_key",
]

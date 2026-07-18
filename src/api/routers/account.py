"""Lightweight account endpoints for the web portal."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from api.auth import ApiKeyContext, _legacy_match
from api.db import auth_db
from api.safe_errors import public_model_list
from api.setting import LEGACY_KEY_ID

security = HTTPBearer()

router = APIRouter(prefix="", tags=["account"])


class MeResponse(BaseModel):
    key_id: str
    name: str
    is_legacy: bool
    rpm_limit: int | None = None
    monthly_token_quota: int | None = None
    usage_month: str | None = None
    prompt_tokens_month: int = 0
    completion_tokens_month: int = 0
    total_tokens_month: int = 0
    remaining_tokens_month: int | None = None
    request_count_month: int = 0
    last_used_at: str | None = None
    revoked: bool = False
    allowed_models: list[str] = []


async def api_key_identify(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
) -> ApiKeyContext:
    """Validate API key without consuming RPM/quota (for /me and UI bootstrap)."""
    token = credentials.credentials
    if _legacy_match(token):
        return ApiKeyContext(key_id=LEGACY_KEY_ID, name="legacy", is_legacy=True)

    record = await asyncio.to_thread(auth_db.authenticate, token)
    if not record:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key")
    return ApiKeyContext(key_id=record.key_id, name=record.name, is_legacy=False)


@router.get("/me", response_model=MeResponse)
async def me(key: Annotated[ApiKeyContext, Depends(api_key_identify)]):
    if key.is_legacy or key.key_id == LEGACY_KEY_ID:
        return MeResponse(
            key_id=LEGACY_KEY_ID,
            name="legacy",
            is_legacy=True,
            rpm_limit=None,
            monthly_token_quota=None,
        )
    record = await asyncio.to_thread(auth_db.get_key, key.key_id)
    if not record:
        raise HTTPException(status_code=404, detail="API key not found")
    return MeResponse(
        key_id=record.key_id,
        name=record.name,
        is_legacy=False,
        rpm_limit=record.rpm_limit,
        monthly_token_quota=record.monthly_token_quota,
        usage_month=record.usage_month,
        prompt_tokens_month=record.prompt_tokens_month,
        completion_tokens_month=record.completion_tokens_month,
        total_tokens_month=record.total_tokens_month,
        remaining_tokens_month=(
            max(0, record.monthly_token_quota - record.total_tokens_month)
            if record.monthly_token_quota > 0
            else None
        ),
        request_count_month=record.request_count_month,
        last_used_at=record.last_used_at,
        revoked=record.revoked,
        allowed_models=public_model_list(record.allowed_models_list),
    )


class UsageLogPublic(BaseModel):
    id: int
    endpoint: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    total_tokens: int
    client_ip: str
    latency_ms: int
    created_at: str


class UsageLogsResponse(BaseModel):
    total: int
    limit: int
    offset: int
    logs: list[UsageLogPublic]


@router.get("/usage/logs", response_model=UsageLogsResponse)
async def usage_logs(
    key: Annotated[ApiKeyContext, Depends(api_key_identify)],
    limit: int = 100,
    offset: int = 0,
):
    if key.is_legacy or key.key_id == LEGACY_KEY_ID:
        return UsageLogsResponse(total=0, limit=limit, offset=offset, logs=[])
    safe_limit = max(1, min(limit, 500))
    safe_offset = max(0, offset)

    def _fetch():
        rows = auth_db.list_usage_logs(key.key_id, limit=safe_limit, offset=safe_offset)
        total = auth_db.count_usage_logs(key.key_id)
        return total, rows

    total, records = await asyncio.to_thread(_fetch)
    return UsageLogsResponse(
        total=total,
        limit=safe_limit,
        offset=safe_offset,
        logs=[
            UsageLogPublic(
                id=item.id,
                endpoint=item.endpoint,
                model=item.model,
                prompt_tokens=item.prompt_tokens,
                completion_tokens=item.completion_tokens,
                cache_read_tokens=item.cache_read_tokens,
                cache_write_tokens=item.cache_write_tokens,
                total_tokens=item.total_tokens,
                client_ip=item.client_ip,
                latency_ms=item.latency_ms,
                created_at=item.created_at,
            )
            for item in records
        ],
    )


class RedeemRequest(BaseModel):
    cdk: str = Field(..., min_length=8, max_length=64)


class RedeemResponse(BaseModel):
    api_key: str
    key_id: str
    name: str
    rpm_limit: int
    monthly_token_quota: int
    allowed_models: list[str] = []
    note: str = "Lưu API key ngay. CDK chỉ dùng một lần."


@router.post("/redeem", response_model=RedeemResponse)
async def redeem_cdk(body: RedeemRequest):
    try:
        _cdk, record, plaintext = await asyncio.to_thread(auth_db.redeem_cdk, body.cdk)
    except KeyError:
        raise HTTPException(status_code=404, detail="CDK không tồn tại") from None
    except PermissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedeemResponse(
        api_key=plaintext,
        key_id=record.key_id,
        name=record.name,
        rpm_limit=record.rpm_limit,
        monthly_token_quota=record.monthly_token_quota,
        allowed_models=public_model_list(record.allowed_models_list),
    )

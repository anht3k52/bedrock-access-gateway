"""Admin API: login, keys, and CDK management."""

from __future__ import annotations

import asyncio
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from api.auth import admin_api_key_auth
from api.db import (
    AdminLoginLogRecord,
    ApiKeyRecord,
    AwsCredentialRecord,
    BannedIpRecord,
    CdkRecord,
    RequestLogRecord,
    auth_db,
)
from api.models.bedrock import BedrockModel, invalidate_aws_credential_clients
from api.safe_errors import scrub_log_error
from api.security import (
    admin_login_limiter,
    mark_ip_banned,
    mark_ip_unbanned,
    verify_password_sha256,
)
from api import setting as setting_mod
from api.setting import (
    DEFAULT_MONTHLY_TOKEN_QUOTA,
    DEFAULT_RPM_LIMIT,
)

router = APIRouter(prefix="", tags=["admin"])


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)
    otp: str = Field(default="", max_length=16)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: str
    username: str


class Admin2faStatus(BaseModel):
    enabled: bool
    updated_at: str = ""


class Admin2faGenerateResponse(BaseModel):
    secret: str
    otpauth_url: str
    otp: str = ""
    message: str = "Thêm secret vào Google Authenticator / Aegis. Mỗi lần login dùng mã 6 số đang hiện trên app."


class CreateKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    rpm_limit: int | None = Field(default=None, ge=0)
    monthly_token_quota: int | None = Field(default=None, ge=0)
    allowed_models: list[str] | None = Field(default=None)


class UpdateKeyRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    rpm_limit: int | None = Field(default=None, ge=0)
    monthly_token_quota: int | None = Field(default=None, ge=0)
    allowed_models: list[str] | None = Field(default=None)


class KeyPublic(BaseModel):
    key_id: str
    name: str
    rpm_limit: int
    monthly_token_quota: int
    revoked: bool
    created_at: str
    last_used_at: str | None
    usage_month: str
    prompt_tokens_month: int
    completion_tokens_month: int
    total_tokens_month: int
    request_count_month: int
    allowed_models: list[str] = []


class CreateKeyResponse(KeyPublic):
    api_key: str
    note: str = "Store this API key now. It will not be shown again."


class CreateCdkRequest(BaseModel):
    label: str = Field(default="user", min_length=1, max_length=64)
    count: int = Field(default=1, ge=1, le=1000)
    rpm_limit: int | None = Field(default=None, ge=0)
    monthly_token_quota: int | None = Field(default=None, ge=0)
    allowed_models: list[str] | None = Field(default=None)


class CdkPublic(BaseModel):
    code: str
    label: str
    rpm_limit: int
    monthly_token_quota: int
    created_at: str
    redeemed_at: str | None
    key_id: str | None
    revoked: bool
    status: str
    allowed_models: list[str] = []


class UsageBucketPublic(BaseModel):
    label: str
    prompt_tokens: int
    completion_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    total_tokens: int
    request_count: int


class UsageByKeyPublic(BaseModel):
    key_id: str
    key_name: str
    prompt_tokens: int
    completion_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    total_tokens: int
    request_count: int
    key_deleted: bool


class UsageSummaryResponse(BaseModel):
    period: str
    date_from: str
    date_to: str
    prompt_tokens: int
    completion_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    total_tokens: int
    request_count: int
    buckets: list[UsageBucketPublic]
    by_key: list[UsageByKeyPublic]


def _to_public(record: ApiKeyRecord) -> KeyPublic:
    return KeyPublic(
        key_id=record.key_id,
        name=record.name,
        rpm_limit=record.rpm_limit,
        monthly_token_quota=record.monthly_token_quota,
        revoked=record.revoked,
        created_at=record.created_at,
        last_used_at=record.last_used_at,
        usage_month=record.usage_month,
        prompt_tokens_month=record.prompt_tokens_month,
        completion_tokens_month=record.completion_tokens_month,
        total_tokens_month=record.total_tokens_month,
        request_count_month=record.request_count_month,
        allowed_models=record.allowed_models_list,
    )


def _cdk_public(record: CdkRecord) -> CdkPublic:
    return CdkPublic(
        code=record.code,
        label=record.label,
        rpm_limit=record.rpm_limit,
        monthly_token_quota=record.monthly_token_quota,
        created_at=record.created_at,
        redeemed_at=record.redeemed_at,
        key_id=record.key_id,
        revoked=record.revoked,
        status=record.status,
        allowed_models=record.allowed_models_list,
    )


def _client_ip(request: Request) -> str:
    cloudflare_ip = request.headers.get("cf-connecting-ip")
    if cloudflare_ip:
        return cloudflare_ip.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


async def _note_login_failure(client_ip: str, detail: str, user_agent: str = "") -> tuple[int, bool]:
    await asyncio.to_thread(
        auth_db.insert_admin_login_log,
        client_ip=client_ip,
        success=False,
        detail=detail,
        user_agent=user_agent,
    )
    fail_count, newly_banned = await asyncio.to_thread(
        auth_db.record_admin_login_failure,
        client_ip,
        ban_after=setting_mod.ADMIN_LOGIN_MAX_FAILURES,
    )
    if newly_banned:
        mark_ip_banned(client_ip)
    return fail_count, newly_banned


@router.post("/login", response_model=LoginResponse)
async def admin_login(body: LoginRequest, request: Request):
    username = setting_mod.ADMIN_USERNAME
    password_hash = setting_mod.ADMIN_PASSWORD_SHA256
    password_salt = setting_mod.ADMIN_PASSWORD_SALT
    password_plain = setting_mod.ADMIN_PASSWORD
    if not password_hash and not password_plain:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin password is not configured",
        )

    client_ip = _client_ip(request)
    user_agent = (request.headers.get("user-agent") or "")[:256]
    admin_login_limiter.max_failures = setting_mod.ADMIN_LOGIN_MAX_FAILURES
    admin_login_limiter.lockout_seconds = setting_mod.ADMIN_LOGIN_LOCKOUT_SECONDS
    blocked, retry_after = admin_login_limiter.is_blocked(client_ip)
    if blocked:
        await asyncio.to_thread(
            auth_db.insert_admin_login_log,
            client_ip=client_ip,
            success=False,
            detail="locked_out",
            user_agent=user_agent,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Quá nhiều lần đăng nhập sai. Thử lại sau {retry_after}s",
            headers={"Retry-After": str(retry_after)},
        )

    user_ok = secrets.compare_digest(body.username.strip(), username)
    pass_ok = verify_password_sha256(
        body.password,
        password_hash,
        salt=password_salt or "",
        plaintext_fallback=password_plain,
    )
    if not (user_ok and pass_ok):
        fail_count, newly_banned = await _note_login_failure(
            client_ip, "bad_credentials", user_agent
        )
        if newly_banned:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Sai mật khẩu quá {fail_count} lần. IP đã bị ban.",
            )
        locked, retry_after = admin_login_limiter.register_failure(client_ip)
        if locked:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Sai mật khẩu quá nhiều lần. Khóa {retry_after}s",
                headers={"Retry-After": str(retry_after)},
            )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sai tài khoản hoặc mật khẩu")

    # Password OK — require 6-digit 2FA when configured.
    twofa_on = await asyncio.to_thread(auth_db.admin_2fa_enabled)
    if twofa_on:
        otp_ok = await asyncio.to_thread(auth_db.verify_admin_2fa_pin, body.otp)
        if not otp_ok:
            fail_count, newly_banned = await _note_login_failure(
                client_ip, "bad_2fa", user_agent
            )
            if newly_banned:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Sai mã 2FA quá {fail_count} lần. IP đã bị ban.",
                )
            locked, retry_after = admin_login_limiter.register_failure(client_ip)
            if locked:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Sai mã 2FA quá nhiều lần. Khóa {retry_after}s",
                    headers={"Retry-After": str(retry_after)},
                )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sai mã 2FA")

    admin_login_limiter.register_success(client_ip)
    await asyncio.to_thread(auth_db.clear_admin_login_failures, client_ip)
    await asyncio.to_thread(
        auth_db.insert_admin_login_log,
        client_ip=client_ip,
        success=True,
        detail="ok",
        user_agent=user_agent,
    )
    # Drop every prior session so password/session changes kick old browsers.
    await asyncio.to_thread(auth_db.revoke_all_admin_sessions)

    def _create_session():
        return auth_db.create_admin_session(hours=setting_mod.ADMIN_SESSION_HOURS)

    token, expires_at = await asyncio.to_thread(_create_session)
    return LoginResponse(access_token=token, expires_at=expires_at, username=username)


@router.post("/logout")
async def admin_logout(token: str = Depends(admin_api_key_auth)):
    await asyncio.to_thread(auth_db.revoke_admin_session, token)
    return {"ok": True}


@router.get("/models", response_model=list[str])
async def list_available_models(_: str = Depends(admin_api_key_auth)):
    # Public short model IDs for admin pickers.
    from api.model_alias import list_public_ids

    def _fetch():
        return list_public_ids(BedrockModel().list_models())

    return await asyncio.to_thread(_fetch)


@router.post("/keys", response_model=CreateKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_key(body: CreateKeyRequest, _: str = Depends(admin_api_key_auth)):
    record, plaintext = auth_db.create_key(
        name=body.name,
        rpm_limit=body.rpm_limit if body.rpm_limit is not None else DEFAULT_RPM_LIMIT,
        monthly_token_quota=(
            body.monthly_token_quota
            if body.monthly_token_quota is not None
            else DEFAULT_MONTHLY_TOKEN_QUOTA
        ),
        allowed_models=body.allowed_models,
    )
    public = _to_public(record)
    return CreateKeyResponse(**public.model_dump(), api_key=plaintext)


@router.get("/keys", response_model=list[KeyPublic])
async def list_keys(include_revoked: bool = False, _: str = Depends(admin_api_key_auth)):
    records = await asyncio.to_thread(auth_db.list_keys, include_revoked)
    return [_to_public(r) for r in records]


@router.get("/keys/{key_id}", response_model=KeyPublic)
async def get_key(key_id: str, _: str = Depends(admin_api_key_auth)):
    record = auth_db.get_key(key_id)
    if not record:
        raise HTTPException(status_code=404, detail="API key not found")
    return _to_public(record)


@router.patch("/keys/{key_id}", response_model=KeyPublic)
async def update_key(key_id: str, body: UpdateKeyRequest, _: str = Depends(admin_api_key_auth)):
    record = auth_db.update_key(
        key_id,
        name=body.name,
        rpm_limit=body.rpm_limit,
        monthly_token_quota=body.monthly_token_quota,
        allowed_models=body.allowed_models,
    )
    if not record:
        raise HTTPException(status_code=404, detail="API key not found")
    return _to_public(record)


@router.delete("/keys/{key_id}", response_model=KeyPublic)
async def revoke_key(key_id: str, _: str = Depends(admin_api_key_auth)):
    record = auth_db.revoke_key(key_id)
    if not record:
        raise HTTPException(status_code=404, detail="API key not found")
    return _to_public(record)


@router.delete("/keys/{key_id}/hard", response_model=KeyPublic)
async def delete_key_hard(key_id: str, _: str = Depends(admin_api_key_auth)):
    record = auth_db.delete_key(key_id)
    if not record:
        raise HTTPException(status_code=404, detail="API key not found")
    return _to_public(record)


@router.get("/usage/summary", response_model=UsageSummaryResponse)
async def usage_summary(
    _: str = Depends(admin_api_key_auth),
    period: str = "day",
    day: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
):
    try:
        data = await asyncio.to_thread(
            lambda: auth_db.usage_summary(
                period=period,
                day=day,
                date_from=date_from,
                date_to=date_to,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return UsageSummaryResponse(
        period=data["period"],
        date_from=data["date_from"],
        date_to=data["date_to"],
        prompt_tokens=data["prompt_tokens"],
        completion_tokens=data["completion_tokens"],
        cache_read_tokens=data["cache_read_tokens"],
        cache_write_tokens=data["cache_write_tokens"],
        total_tokens=data["total_tokens"],
        request_count=data["request_count"],
        buckets=[UsageBucketPublic(**b.__dict__) for b in data["buckets"]],
        by_key=[UsageByKeyPublic(**k.__dict__) for k in data["by_key"]],
    )


@router.post("/cdks", response_model=list[CdkPublic], status_code=status.HTTP_201_CREATED)
async def create_cdks(body: CreateCdkRequest, _: str = Depends(admin_api_key_auth)):
    records = auth_db.create_cdks(
        count=body.count,
        label=body.label,
        rpm_limit=body.rpm_limit if body.rpm_limit is not None else DEFAULT_RPM_LIMIT,
        monthly_token_quota=(
            body.monthly_token_quota
            if body.monthly_token_quota is not None
            else DEFAULT_MONTHLY_TOKEN_QUOTA
        ),
        allowed_models=body.allowed_models,
    )
    return [_cdk_public(r) for r in records]


@router.get("/cdks", response_model=list[CdkPublic])
async def list_cdks(include_redeemed: bool = True, _: str = Depends(admin_api_key_auth)):
    records = await asyncio.to_thread(auth_db.list_cdks, include_redeemed)
    return [_cdk_public(r) for r in records]


@router.delete("/cdks/{code}", response_model=CdkPublic)
async def revoke_cdk(code: str, _: str = Depends(admin_api_key_auth)):
    record = auth_db.revoke_cdk(code)
    if not record:
        raise HTTPException(status_code=404, detail="CDK not found")
    return _cdk_public(record)


@router.delete("/cdks/{code}/hard", response_model=CdkPublic)
async def delete_cdk_hard(code: str, _: str = Depends(admin_api_key_auth)):
    record = auth_db.delete_cdk(code)
    if not record:
        raise HTTPException(status_code=404, detail="CDK not found")
    return _cdk_public(record)


# --- AWS Access Key pool ---


class CreateAwsCredentialRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    access_key_id: str = Field(..., min_length=16, max_length=128)
    secret_access_key: str = Field(..., min_length=8, max_length=256)
    session_token: str | None = Field(default="", max_length=2048)
    region: str | None = Field(default="", max_length=64)
    allowed_models: list[str] | None = Field(default=None)
    priority: int = Field(default=100, ge=0, le=10000)
    enabled: bool = True


class UpdateAwsCredentialRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    access_key_id: str | None = Field(default=None, min_length=16, max_length=128)
    secret_access_key: str | None = Field(default=None, min_length=8, max_length=256)
    session_token: str | None = Field(default=None, max_length=2048)
    region: str | None = Field(default=None, max_length=64)
    allowed_models: list[str] | None = Field(default=None)
    priority: int | None = Field(default=None, ge=0, le=10000)
    enabled: bool | None = None


class AwsModelUsagePublic(BaseModel):
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    request_count: int


class AwsCredentialPublic(BaseModel):
    cred_id: str
    name: str
    access_key_id_masked: str
    region: str
    allowed_models: list[str] = []
    priority: int
    enabled: bool
    is_default: bool = False
    created_at: str
    last_used_at: str | None
    usage_month: str = ""
    prompt_tokens_month: int = 0
    completion_tokens_month: int = 0
    total_tokens_month: int = 0
    request_count_month: int = 0
    models_usage: list[AwsModelUsagePublic] = []


def _mask_access_key(access_key_id: str) -> str:
    ak = (access_key_id or "").strip()
    if len(ak) <= 8:
        return "****"
    return f"{ak[:4]}…{ak[-4:]}"


def _aws_public(r: AwsCredentialRecord, models_usage: list | None = None) -> AwsCredentialPublic:
    return AwsCredentialPublic(
        cred_id=r.cred_id,
        name=r.name,
        access_key_id_masked=_mask_access_key(r.access_key_id),
        region=r.region or "",
        allowed_models=r.allowed_models_list,
        priority=r.priority,
        enabled=r.enabled,
        is_default=bool(r.is_default),
        created_at=r.created_at,
        last_used_at=r.last_used_at,
        usage_month=r.usage_month or "",
        prompt_tokens_month=int(r.prompt_tokens_month or 0),
        completion_tokens_month=int(r.completion_tokens_month or 0),
        total_tokens_month=int(r.total_tokens_month),
        request_count_month=int(r.request_count_month or 0),
        models_usage=[AwsModelUsagePublic(**m) for m in (models_usage or [])],
    )


@router.get("/aws-credentials", response_model=list[AwsCredentialPublic])
async def list_aws_credentials(_: str = Depends(admin_api_key_auth)):
    def _fetch():
        records = auth_db.list_aws_credentials(True)
        out = []
        for r in records:
            models = auth_db.aws_usage_by_model(r.cred_id, limit=12)
            out.append(_aws_public(r, models))
        return out

    return await asyncio.to_thread(_fetch)


@router.post(
    "/aws-credentials",
    response_model=AwsCredentialPublic,
    status_code=status.HTTP_201_CREATED,
)
async def create_aws_credential(
    body: CreateAwsCredentialRequest, _: str = Depends(admin_api_key_auth)
):
    try:
        record = await asyncio.to_thread(
            lambda: auth_db.create_aws_credential(
                name=body.name,
                access_key_id=body.access_key_id,
                secret_access_key=body.secret_access_key,
                session_token=body.session_token or "",
                region=body.region or "",
                allowed_models=body.allowed_models,
                priority=body.priority,
                enabled=body.enabled,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    invalidate_aws_credential_clients(record.cred_id)
    return _aws_public(record)


@router.patch("/aws-credentials/{cred_id}", response_model=AwsCredentialPublic)
async def update_aws_credential(
    cred_id: str, body: UpdateAwsCredentialRequest, _: str = Depends(admin_api_key_auth)
):
    record = await asyncio.to_thread(
        lambda: auth_db.update_aws_credential(
            cred_id,
            name=body.name,
            access_key_id=body.access_key_id,
            secret_access_key=body.secret_access_key,
            session_token=body.session_token,
            region=body.region,
            allowed_models=body.allowed_models,
            priority=body.priority,
            enabled=body.enabled,
        )
    )
    if not record:
        raise HTTPException(status_code=404, detail="Upstream credential not found")
    invalidate_aws_credential_clients(cred_id)
    return _aws_public(record)


@router.delete("/aws-credentials/{cred_id}", response_model=AwsCredentialPublic)
async def delete_aws_credential(cred_id: str, _: str = Depends(admin_api_key_auth)):
    record = await asyncio.to_thread(auth_db.delete_aws_credential, cred_id)
    if not record:
        raise HTTPException(status_code=404, detail="Upstream credential not found")
    invalidate_aws_credential_clients(cred_id)
    return _aws_public(record)


@router.post("/aws-credentials/{cred_id}/default", response_model=AwsCredentialPublic)
async def set_default_aws_credential(cred_id: str, _: str = Depends(admin_api_key_auth)):
    record = await asyncio.to_thread(auth_db.set_default_aws_credential, cred_id)
    if not record:
        raise HTTPException(status_code=404, detail="Upstream credential not found")
    return _aws_public(record, await asyncio.to_thread(auth_db.aws_usage_by_model, cred_id, 12))


class RequestLogPublic(BaseModel):
    id: int
    created_at: str
    method: str
    path: str
    status_code: int
    client_ip: str
    latency_ms: int
    key_id: str = ""
    error: str = ""
    user_agent: str = ""


class RequestLogsResponse(BaseModel):
    total: int
    limit: int
    offset: int
    logs: list[RequestLogPublic]


class RequestLogIpSummaryPublic(BaseModel):
    client_ip: str
    request_count: int
    error_count: int
    last_seen: str


def _request_log_public(r: RequestLogRecord) -> RequestLogPublic:
    return RequestLogPublic(
        id=r.id,
        created_at=r.created_at,
        method=r.method,
        path=r.path,
        status_code=r.status_code,
        client_ip=r.client_ip,
        latency_ms=r.latency_ms,
        key_id=r.key_id,
        error=scrub_log_error(r.error),
        user_agent=r.user_agent,
    )


@router.get("/request-logs", response_model=RequestLogsResponse)
async def list_request_logs(
    limit: int = 50,
    offset: int = 0,
    ip: str | None = None,
    method: str | None = None,
    status: str | None = None,
    path: str | None = None,
    errors_only: bool = False,
    date_from: str | None = None,
    date_to: str | None = None,
    _: str = Depends(admin_api_key_auth),
):
    """HTTP access log for spam / error inspection (not billing usage_logs)."""
    status_min = status_max = None
    band = (status or "").strip().lower()
    if band in ("2xx", "ok"):
        status_min, status_max = 200, 299
    elif band in ("4xx", "client"):
        status_min, status_max = 400, 499
    elif band in ("5xx", "server"):
        status_min, status_max = 500, 599
    elif band.isdigit():
        status_min = status_max = int(band)

    safe_limit = max(1, min(int(limit), 500))
    safe_offset = max(0, int(offset))
    filters = dict(
        ip=ip or None,
        method=(method or None),
        status_min=status_min,
        status_max=status_max,
        path_contains=path or None,
        errors_only=bool(errors_only),
        date_from=date_from or None,
        date_to=date_to or None,
    )

    def _fetch():
        total = auth_db.count_request_logs(**filters)
        rows = auth_db.list_request_logs(limit=safe_limit, offset=safe_offset, **filters)
        return total, rows

    total, rows = await asyncio.to_thread(_fetch)
    return RequestLogsResponse(
        total=total,
        limit=safe_limit,
        offset=safe_offset,
        logs=[_request_log_public(r) for r in rows],
    )


@router.get("/request-logs/ip-summary", response_model=list[RequestLogIpSummaryPublic])
async def request_logs_ip_summary(
    hours: int = 24,
    limit: int = 30,
    _: str = Depends(admin_api_key_auth),
):
    rows = await asyncio.to_thread(auth_db.request_log_ip_summary, hours=hours, limit=limit)
    return [
        RequestLogIpSummaryPublic(
            client_ip=r.client_ip,
            request_count=r.request_count,
            error_count=r.error_count,
            last_seen=r.last_seen,
        )
        for r in rows
    ]


class BannedIpPublic(BaseModel):
    ip: str
    reason: str = ""
    source: str = ""
    created_at: str = ""


class BanIpRequest(BaseModel):
    ip: str = Field(..., min_length=3, max_length=128)
    reason: str = Field(default="", max_length=256)


def _banned_ip_public(r: BannedIpRecord) -> BannedIpPublic:
    return BannedIpPublic(
        ip=r.ip,
        reason=r.reason,
        source=r.source,
        created_at=r.created_at,
    )


@router.get("/banned-ips", response_model=list[BannedIpPublic])
async def list_banned_ips(_: str = Depends(admin_api_key_auth)):
    rows = await asyncio.to_thread(auth_db.list_banned_ips)
    return [_banned_ip_public(r) for r in rows]


@router.post("/banned-ips", response_model=BannedIpPublic, status_code=status.HTTP_201_CREATED)
async def ban_ip(body: BanIpRequest, _: str = Depends(admin_api_key_auth)):
    try:
        record = await asyncio.to_thread(
            auth_db.ban_ip,
            body.ip,
            reason=(body.reason or "Manual ban from Check Log").strip() or "Manual ban",
            source="manual",
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    mark_ip_banned(record.ip)
    return _banned_ip_public(record)


@router.delete("/banned-ips/{ip:path}", response_model=BannedIpPublic)
async def unban_ip(ip: str, _: str = Depends(admin_api_key_auth)):
    record = await asyncio.to_thread(auth_db.unban_ip, ip)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IP not banned")
    mark_ip_unbanned(record.ip)
    return _banned_ip_public(record)


class AdminLoginLogPublic(BaseModel):
    id: int
    created_at: str
    client_ip: str
    success: bool
    detail: str = ""
    user_agent: str = ""


class AdminLoginLogsResponse(BaseModel):
    total: int
    limit: int
    offset: int
    logs: list[AdminLoginLogPublic]


def _admin_login_log_public(r: AdminLoginLogRecord) -> AdminLoginLogPublic:
    return AdminLoginLogPublic(
        id=r.id,
        created_at=r.created_at,
        client_ip=r.client_ip,
        success=r.success,
        detail=r.detail,
        user_agent=r.user_agent,
    )


@router.get("/login-logs", response_model=AdminLoginLogsResponse)
async def list_admin_login_logs(
    limit: int = 100,
    offset: int = 0,
    _: str = Depends(admin_api_key_auth),
):
    safe_limit = max(1, min(int(limit), 500))
    safe_offset = max(0, int(offset))

    def _fetch():
        total = auth_db.count_admin_login_logs()
        rows = auth_db.list_admin_login_logs(limit=safe_limit, offset=safe_offset)
        return total, rows

    total, rows = await asyncio.to_thread(_fetch)
    return AdminLoginLogsResponse(
        total=total,
        limit=safe_limit,
        offset=safe_offset,
        logs=[_admin_login_log_public(r) for r in rows],
    )


@router.get("/2fa", response_model=Admin2faStatus)
async def admin_2fa_status(_: str = Depends(admin_api_key_auth)):
    enabled = await asyncio.to_thread(auth_db.admin_2fa_enabled)
    updated = await asyncio.to_thread(auth_db.get_setting, "admin_2fa_updated_at", "")
    return Admin2faStatus(enabled=enabled, updated_at=updated or "")


@router.post("/2fa/generate", response_model=Admin2faGenerateResponse)
async def admin_2fa_generate(_: str = Depends(admin_api_key_auth)):
    """Rotate admin TOTP secret (authenticator app). Secret returned once."""
    from api.security import totp_code, totp_provisioning_uri

    secret = await asyncio.to_thread(auth_db.generate_admin_totp_secret)
    uri = totp_provisioning_uri(
        secret,
        account_name=setting_mod.ADMIN_USERNAME or "admin",
        issuer="MRDEV Gateway",
    )
    return Admin2faGenerateResponse(
        secret=secret,
        otpauth_url=uri,
        otp=totp_code(secret),
    )

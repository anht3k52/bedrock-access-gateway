"""SQLite storage for API keys, quotas, and usage accounting."""

from __future__ import annotations

import hashlib
import logging
import os
import queue
import secrets
import sqlite3
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Deque

_log = logging.getLogger(__name__)

from api.setting import (
    AUTH_DB_PATH,
    DEFAULT_MONTHLY_TOKEN_QUOTA,
    DEFAULT_RPM_LIMIT,
    LEGACY_KEY_ID,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _month_key(dt: datetime | None = None) -> str:
    dt = dt or _utcnow()
    return dt.strftime("%Y-%m")


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def parse_allowed_models(value: str | None) -> list[str]:
    if not value:
        return []
    return [m.strip() for m in value.split(",") if m.strip()]


def normalize_allowed_models(models: list[str] | str | None) -> str:
    if models is None:
        return ""
    if isinstance(models, str):
        items = parse_allowed_models(models)
    else:
        items = [str(m).strip() for m in models if str(m).strip()]
    seen: dict[str, None] = {}
    for m in items:
        seen.setdefault(m, None)
    return ",".join(seen.keys())


_REGION_PREFIXES = ("us.", "eu.", "apac.", "global.", "jp.", "au.", "ca.", "us-gov.")


def model_id_aliases(model: str) -> set[str]:
    """Match cross-region / mrdev public IDs to the same logical model."""
    from api.model_alias import alias_set

    m = (model or "").strip()
    if not m:
        return set()
    aliases = set(alias_set(m))
    base = m
    for prefix in _REGION_PREFIXES:
        if m.startswith(prefix):
            base = m[len(prefix) :]
            aliases.add(base)
            break
    if base.startswith(("anthropic.", "amazon.", "meta.", "mistral.", "cohere.")):
        for prefix in ("us.", "global.", "eu.", "apac."):
            aliases.add(prefix + base)
    return aliases


def model_in_allowlist(model: str, allowed: list[str], *, tier_mode: bool = False) -> bool:
    if not allowed:
        return False
    if tier_mode:
        from api.model_alias import model_allowed_by_tiers

        tier_hit = model_allowed_by_tiers(model, allowed)
        if tier_hit is not None:
            return tier_hit
    wanted = model_id_aliases(model)
    for item in allowed:
        if wanted & model_id_aliases(item):
            return True
    return False


@dataclass
class ApiKeyRecord:
    key_id: str
    name: str
    secret_hash: str
    rpm_limit: int
    monthly_token_quota: int
    revoked: bool
    created_at: str
    last_used_at: str | None
    usage_month: str
    prompt_tokens_month: int
    completion_tokens_month: int
    request_count_month: int
    allowed_models: str = ""

    @property
    def total_tokens_month(self) -> int:
        return self.prompt_tokens_month + self.completion_tokens_month

    @property
    def allowed_models_list(self) -> list[str]:
        return parse_allowed_models(self.allowed_models)

    def is_model_allowed(self, model: str) -> bool:
        allowed = self.allowed_models_list
        if not allowed:
            return True
        # Key/CDK allowlists use tier ceilings (4.6 / 4.8 / fable5).
        return model_in_allowlist(model, allowed, tier_mode=True)


@dataclass
class CdkRecord:
    code: str
    label: str
    rpm_limit: int
    monthly_token_quota: int
    created_at: str
    redeemed_at: str | None
    key_id: str | None
    revoked: bool
    allowed_models: str = ""

    @property
    def allowed_models_list(self) -> list[str]:
        return parse_allowed_models(self.allowed_models)

    @property
    def status(self) -> str:
        if self.revoked:
            return "revoked"
        if self.redeemed_at:
            return "redeemed"
        return "available"


@dataclass
class UsageLogRecord:
    id: int
    key_id: str
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
    key_name: str = ""


@dataclass
class UsageBucket:
    label: str
    prompt_tokens: int
    completion_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    total_tokens: int
    request_count: int


@dataclass
class UsageByKey:
    key_id: str
    key_name: str
    prompt_tokens: int
    completion_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    total_tokens: int
    request_count: int
    key_deleted: bool


@dataclass
class AwsCredentialRecord:
    cred_id: str
    name: str
    access_key_id: str
    secret_access_key: str
    session_token: str
    region: str
    allowed_models: str
    priority: int
    enabled: bool
    created_at: str
    last_used_at: str | None
    is_default: bool = False
    usage_month: str = ""
    prompt_tokens_month: int = 0
    completion_tokens_month: int = 0
    request_count_month: int = 0

    @property
    def total_tokens_month(self) -> int:
        return int(self.prompt_tokens_month or 0) + int(self.completion_tokens_month or 0)

    @property
    def allowed_models_list(self) -> list[str]:
        return parse_allowed_models(self.allowed_models)

    def is_model_allowed(self, model: str) -> bool:
        """Empty allowlist = allow all; otherwise match with region-prefix aliases."""
        allowed = self.allowed_models_list
        if not allowed:
            return True
        return model_in_allowlist(model, allowed)

    def explicitly_allows_model(self, model: str) -> bool:
        """True only when this key lists the model (not wildcard/empty)."""
        return model_in_allowlist(model, self.allowed_models_list)


@dataclass
class RequestLogRecord:
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


@dataclass
class RequestLogIpSummary:
    client_ip: str
    request_count: int
    error_count: int
    last_seen: str


@dataclass
class BannedIpRecord:
    ip: str
    reason: str
    source: str
    created_at: str


@dataclass
class AdminLoginLogRecord:
    id: int
    created_at: str
    client_ip: str
    success: bool
    detail: str
    user_agent: str = ""


class AuthDatabase:
    def __init__(self, db_path: str = AUTH_DB_PATH):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._request_windows: dict[str, Deque[float]] = defaultdict(deque)
        os.makedirs(os.path.dirname(os.path.abspath(db_path)) or ".", exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS api_keys (
                        key_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        secret_hash TEXT NOT NULL,
                        rpm_limit INTEGER NOT NULL,
                        monthly_token_quota INTEGER NOT NULL,
                        revoked INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        last_used_at TEXT,
                        usage_month TEXT NOT NULL,
                        prompt_tokens_month INTEGER NOT NULL DEFAULT 0,
                        completion_tokens_month INTEGER NOT NULL DEFAULT 0,
                        request_count_month INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS admin_sessions (
                        token_hash TEXT PRIMARY KEY,
                        created_at TEXT NOT NULL,
                        expires_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cdks (
                        code TEXT PRIMARY KEY,
                        label TEXT NOT NULL,
                        rpm_limit INTEGER NOT NULL,
                        monthly_token_quota INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        redeemed_at TEXT,
                        key_id TEXT,
                        revoked INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS usage_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        key_id TEXT NOT NULL,
                        endpoint TEXT NOT NULL,
                        model TEXT NOT NULL,
                        prompt_tokens INTEGER NOT NULL DEFAULT 0,
                        completion_tokens INTEGER NOT NULL DEFAULT 0,
                        cache_read_tokens INTEGER NOT NULL DEFAULT 0,
                        cache_write_tokens INTEGER NOT NULL DEFAULT 0,
                        total_tokens INTEGER NOT NULL DEFAULT 0,
                        client_ip TEXT NOT NULL DEFAULT '',
                        latency_ms INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_usage_logs_key_created
                    ON usage_logs (key_id, created_at DESC)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_usage_logs_created
                    ON usage_logs (created_at DESC)
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS aws_credentials (
                        cred_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        access_key_id TEXT NOT NULL,
                        secret_access_key TEXT NOT NULL,
                        session_token TEXT NOT NULL DEFAULT '',
                        region TEXT NOT NULL DEFAULT '',
                        allowed_models TEXT NOT NULL DEFAULT '',
                        priority INTEGER NOT NULL DEFAULT 100,
                        enabled INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL,
                        last_used_at TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS request_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at TEXT NOT NULL,
                        method TEXT NOT NULL,
                        path TEXT NOT NULL,
                        status_code INTEGER NOT NULL,
                        client_ip TEXT NOT NULL DEFAULT '',
                        latency_ms INTEGER NOT NULL DEFAULT 0,
                        key_id TEXT NOT NULL DEFAULT '',
                        error TEXT NOT NULL DEFAULT '',
                        user_agent TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_request_logs_created
                    ON request_logs (created_at DESC)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_request_logs_ip_created
                    ON request_logs (client_ip, created_at DESC)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_request_logs_status_created
                    ON request_logs (status_code, created_at DESC)
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS banned_ips (
                        ip TEXT PRIMARY KEY,
                        reason TEXT NOT NULL DEFAULT '',
                        source TEXT NOT NULL DEFAULT 'manual',
                        created_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS admin_login_failures (
                        ip TEXT PRIMARY KEY,
                        fail_count INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS admin_login_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at TEXT NOT NULL,
                        client_ip TEXT NOT NULL DEFAULT '',
                        success INTEGER NOT NULL DEFAULT 0,
                        detail TEXT NOT NULL DEFAULT '',
                        user_agent TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_admin_login_logs_created
                    ON admin_login_logs (created_at DESC)
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS admin_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
                self._ensure_column(conn, "api_keys", "allowed_models", "allowed_models TEXT NOT NULL DEFAULT ''")
                self._ensure_column(conn, "cdks", "allowed_models", "allowed_models TEXT NOT NULL DEFAULT ''")
                self._ensure_column(conn, "usage_logs", "key_name", "key_name TEXT NOT NULL DEFAULT ''")
                self._ensure_column(conn, "usage_logs", "aws_cred_id", "aws_cred_id TEXT NOT NULL DEFAULT ''")
                self._ensure_column(conn, "usage_logs", "aws_cred_name", "aws_cred_name TEXT NOT NULL DEFAULT ''")
                self._ensure_column(conn, "aws_credentials", "is_default", "is_default INTEGER NOT NULL DEFAULT 0")
                self._ensure_column(conn, "aws_credentials", "usage_month", "usage_month TEXT NOT NULL DEFAULT ''")
                self._ensure_column(
                    conn, "aws_credentials", "prompt_tokens_month", "prompt_tokens_month INTEGER NOT NULL DEFAULT 0"
                )
                self._ensure_column(
                    conn,
                    "aws_credentials",
                    "completion_tokens_month",
                    "completion_tokens_month INTEGER NOT NULL DEFAULT 0",
                )
                self._ensure_column(
                    conn, "aws_credentials", "request_count_month", "request_count_month INTEGER NOT NULL DEFAULT 0"
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_usage_logs_aws_cred_created
                    ON usage_logs (aws_cred_id, created_at DESC)
                    """
                )
                # Ensure exactly one default AWS key when any exist.
                row = conn.execute(
                    "SELECT cred_id FROM aws_credentials WHERE is_default = 1 LIMIT 1"
                ).fetchone()
                if not row:
                    first = conn.execute(
                        "SELECT cred_id FROM aws_credentials ORDER BY created_at ASC LIMIT 1"
                    ).fetchone()
                    if first:
                        conn.execute(
                            "UPDATE aws_credentials SET is_default = 1 WHERE cred_id = ?",
                            (first["cred_id"],),
                        )
                # Backfill names for logs that still have a living key.
                conn.execute(
                    """
                    UPDATE usage_logs
                    SET key_name = (
                        SELECT name FROM api_keys WHERE api_keys.key_id = usage_logs.key_id
                    )
                    WHERE (key_name IS NULL OR key_name = '')
                      AND EXISTS (SELECT 1 FROM api_keys WHERE api_keys.key_id = usage_logs.key_id)
                    """
                )
                conn.commit()

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
        cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")

    def _row_to_record(self, row: sqlite3.Row) -> ApiKeyRecord:
        keys = row.keys()
        return ApiKeyRecord(
            key_id=row["key_id"],
            name=row["name"],
            secret_hash=row["secret_hash"],
            rpm_limit=row["rpm_limit"],
            monthly_token_quota=row["monthly_token_quota"],
            revoked=bool(row["revoked"]),
            created_at=row["created_at"],
            last_used_at=row["last_used_at"],
            usage_month=row["usage_month"],
            prompt_tokens_month=row["prompt_tokens_month"],
            completion_tokens_month=row["completion_tokens_month"],
            request_count_month=row["request_count_month"],
            allowed_models=row["allowed_models"] if "allowed_models" in keys else "",
        )

    def create_key(
        self,
        name: str,
        rpm_limit: int | None = None,
        monthly_token_quota: int | None = None,
        allowed_models: list[str] | str | None = None,
    ) -> tuple[ApiKeyRecord, str]:
        key_id = secrets.token_hex(8)
        secret = secrets.token_urlsafe(32)
        plaintext = f"bag_{key_id}_{secret}"
        now = _utcnow().isoformat()
        record = ApiKeyRecord(
            key_id=key_id,
            name=name,
            secret_hash=hash_secret(secret),
            rpm_limit=rpm_limit if rpm_limit is not None else DEFAULT_RPM_LIMIT,
            monthly_token_quota=(
                monthly_token_quota if monthly_token_quota is not None else DEFAULT_MONTHLY_TOKEN_QUOTA
            ),
            revoked=False,
            created_at=now,
            last_used_at=None,
            usage_month=_month_key(),
            prompt_tokens_month=0,
            completion_tokens_month=0,
            request_count_month=0,
            allowed_models=normalize_allowed_models(allowed_models),
        )
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO api_keys (
                        key_id, name, secret_hash, rpm_limit, monthly_token_quota,
                        revoked, created_at, last_used_at, usage_month,
                        prompt_tokens_month, completion_tokens_month, request_count_month,
                        allowed_models
                    ) VALUES (?, ?, ?, ?, ?, 0, ?, NULL, ?, 0, 0, 0, ?)
                    """,
                    (
                        record.key_id,
                        record.name,
                        record.secret_hash,
                        record.rpm_limit,
                        record.monthly_token_quota,
                        record.created_at,
                        record.usage_month,
                        record.allowed_models,
                    ),
                )
                conn.commit()
        return record, plaintext

    def list_keys(self, include_revoked: bool = False) -> list[ApiKeyRecord]:
        with self._lock:
            with self._connect() as conn:
                if include_revoked:
                    rows = conn.execute("SELECT * FROM api_keys ORDER BY created_at DESC").fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM api_keys WHERE revoked = 0 ORDER BY created_at DESC"
                    ).fetchall()
        records = [self._ensure_month(self._row_to_record(row)) for row in rows]
        return records

    def get_key(self, key_id: str) -> ApiKeyRecord | None:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM api_keys WHERE key_id = ?", (key_id,)).fetchone()
        if not row:
            return None
        return self._ensure_month(self._row_to_record(row))

    def revoke_key(self, key_id: str) -> ApiKeyRecord | None:
        with self._lock:
            with self._connect() as conn:
                conn.execute("UPDATE api_keys SET revoked = 1 WHERE key_id = ?", (key_id,))
                conn.commit()
                row = conn.execute("SELECT * FROM api_keys WHERE key_id = ?", (key_id,)).fetchone()
        return self._row_to_record(row) if row else None

    def delete_key(self, key_id: str) -> ApiKeyRecord | None:
        """Permanently remove an API key but keep usage_logs for historical reports."""
        record = self.get_key(key_id)
        if not record:
            return None
        with self._lock:
            with self._connect() as conn:
                # Snapshot name onto logs so reports still show who used tokens.
                conn.execute(
                    """
                    UPDATE usage_logs
                    SET key_name = ?
                    WHERE key_id = ? AND (key_name IS NULL OR key_name = '')
                    """,
                    (record.name, key_id),
                )
                conn.execute("DELETE FROM api_keys WHERE key_id = ?", (key_id,))
                conn.commit()
        return record

    def update_key(
        self,
        key_id: str,
        *,
        name: str | None = None,
        rpm_limit: int | None = None,
        monthly_token_quota: int | None = None,
        allowed_models: list[str] | str | None = None,
    ) -> ApiKeyRecord | None:
        record = self.get_key(key_id)
        if not record:
            return None
        new_name = name if name is not None else record.name
        new_rpm = rpm_limit if rpm_limit is not None else record.rpm_limit
        new_quota = monthly_token_quota if monthly_token_quota is not None else record.monthly_token_quota
        new_models = (
            normalize_allowed_models(allowed_models) if allowed_models is not None else record.allowed_models
        )
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE api_keys
                    SET name = ?, rpm_limit = ?, monthly_token_quota = ?, allowed_models = ?
                    WHERE key_id = ?
                    """,
                    (new_name, new_rpm, new_quota, new_models, key_id),
                )
                conn.commit()
        return self.get_key(key_id)

    def authenticate(self, plaintext_key: str) -> ApiKeyRecord | None:
        if not plaintext_key.startswith("bag_"):
            return None
        parts = plaintext_key.split("_", 2)
        if len(parts) != 3:
            return None
        _, key_id, secret = parts
        record = self.get_key(key_id)
        if not record or record.revoked:
            return None
        if not secrets.compare_digest(record.secret_hash, hash_secret(secret)):
            return None
        return record

    def _ensure_month(self, record: ApiKeyRecord) -> ApiKeyRecord:
        current = _month_key()
        if record.usage_month == current:
            return record
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE api_keys
                    SET usage_month = ?, prompt_tokens_month = 0,
                        completion_tokens_month = 0, request_count_month = 0
                    WHERE key_id = ? AND usage_month != ?
                    """,
                    (current, record.key_id, current),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM api_keys WHERE key_id = ?", (record.key_id,)
                ).fetchone()
        return self._row_to_record(row) if row else record

    def check_and_consume_request(self, key_id: str) -> ApiKeyRecord:
        """Validate RPM + monthly token quota and count one request."""
        import time

        record = self.get_key(key_id)
        if not record:
            raise KeyError(f"Unknown key_id: {key_id}")
        if record.revoked:
            raise PermissionError("API key revoked")

        # Unlimited quota when monthly_token_quota <= 0
        if record.monthly_token_quota > 0 and record.total_tokens_month >= record.monthly_token_quota:
            raise QuotaExceededError(
                f"Monthly token quota exceeded ({record.total_tokens_month}/{record.monthly_token_quota})"
            )

        now = time.time()
        with self._lock:
            window = self._request_windows[key_id]
            while window and now - window[0] >= 60:
                window.popleft()
            if record.rpm_limit > 0 and len(window) >= record.rpm_limit:
                raise RateLimitError(f"Rate limit exceeded ({record.rpm_limit} requests/minute)")
            window.append(now)

            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE api_keys
                    SET request_count_month = request_count_month + 1,
                        last_used_at = ?
                    WHERE key_id = ?
                    """,
                    (_utcnow().isoformat(), key_id),
                )
                conn.commit()
        return self.get_key(key_id)  # type: ignore[return-value]

    def record_usage(self, key_id: str, prompt_tokens: int, completion_tokens: int) -> ApiKeyRecord | None:
        if key_id == LEGACY_KEY_ID:
            return None
        record = self.get_key(key_id)
        if not record:
            return None
        self._ensure_month(record)
        prompt_tokens = max(0, int(prompt_tokens or 0))
        completion_tokens = max(0, int(completion_tokens or 0))
        if prompt_tokens == 0 and completion_tokens == 0:
            return self.get_key(key_id)
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE api_keys
                    SET prompt_tokens_month = prompt_tokens_month + ?,
                        completion_tokens_month = completion_tokens_month + ?,
                        last_used_at = ?
                    WHERE key_id = ?
                    """,
                    (prompt_tokens, completion_tokens, _utcnow().isoformat(), key_id),
                )
                conn.commit()
        return self.get_key(key_id)

    def record_request_usage(
        self,
        key_id: str,
        *,
        endpoint: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        client_ip: str = "",
        latency_ms: int = 0,
        aws_cred_id: str = "",
        aws_cred_name: str = "",
    ) -> ApiKeyRecord | None:
        if key_id == LEGACY_KEY_ID:
            return None
        record = self.get_key(key_id)
        if not record:
            return None
        self._ensure_month(record)
        prompt = max(0, int(prompt_tokens or 0))
        completion = max(0, int(completion_tokens or 0))
        cache_read = max(0, int(cache_read_tokens or 0))
        cache_write = max(0, int(cache_write_tokens or 0))
        total = prompt + completion
        now = _utcnow().isoformat()
        aws_id = (aws_cred_id or "")[:64]
        aws_name = (aws_cred_name or "")[:128]
        month = _month_key()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE api_keys
                    SET prompt_tokens_month = prompt_tokens_month + ?,
                        completion_tokens_month = completion_tokens_month + ?,
                        request_count_month = request_count_month + 1,
                        last_used_at = ?
                    WHERE key_id = ?
                    """,
                    (prompt, completion, now, key_id),
                )
                conn.execute(
                    """
                    INSERT INTO usage_logs (
                        key_id, key_name, endpoint, model, prompt_tokens, completion_tokens,
                        cache_read_tokens, cache_write_tokens, total_tokens,
                        client_ip, latency_ms, created_at, aws_cred_id, aws_cred_name
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        key_id,
                        record.name,
                        endpoint,
                        model,
                        prompt,
                        completion,
                        cache_read,
                        cache_write,
                        total,
                        client_ip[:128],
                        max(0, int(latency_ms or 0)),
                        now,
                        aws_id,
                        aws_name,
                    ),
                )
                if aws_id:
                    conn.execute(
                        """
                        UPDATE aws_credentials
                        SET prompt_tokens_month = CASE
                                WHEN usage_month = ? THEN prompt_tokens_month + ?
                                ELSE ?
                            END,
                            completion_tokens_month = CASE
                                WHEN usage_month = ? THEN completion_tokens_month + ?
                                ELSE ?
                            END,
                            request_count_month = CASE
                                WHEN usage_month = ? THEN request_count_month + 1
                                ELSE 1
                            END,
                            usage_month = ?,
                            last_used_at = ?
                        WHERE cred_id = ?
                        """,
                        (
                            month,
                            prompt,
                            prompt,
                            month,
                            completion,
                            completion,
                            month,
                            month,
                            now,
                            aws_id,
                        ),
                    )
                conn.commit()
        return self.get_key(key_id)

    def list_usage_logs(self, key_id: str, limit: int = 100, offset: int = 0) -> list[UsageLogRecord]:
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM usage_logs
                    WHERE key_id = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT ? OFFSET ?
                    """,
                    (key_id, limit, offset),
                ).fetchall()
        return [self._row_to_usage_log(row) for row in rows]

    def count_usage_logs(self, key_id: str) -> int:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS count FROM usage_logs WHERE key_id = ?",
                    (key_id,),
                ).fetchone()
        return int(row["count"]) if row else 0

    def _row_to_usage_log(self, row: sqlite3.Row) -> UsageLogRecord:
        keys = row.keys()
        return UsageLogRecord(
            id=row["id"],
            key_id=row["key_id"],
            endpoint=row["endpoint"],
            model=row["model"],
            prompt_tokens=row["prompt_tokens"],
            completion_tokens=row["completion_tokens"],
            cache_read_tokens=row["cache_read_tokens"],
            cache_write_tokens=row["cache_write_tokens"],
            total_tokens=row["total_tokens"],
            client_ip=row["client_ip"],
            latency_ms=row["latency_ms"],
            created_at=row["created_at"],
            key_name=row["key_name"] if "key_name" in keys else "",
        )

    def usage_summary(
        self,
        *,
        period: str = "day",
        day: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict:
        """Aggregate usage for admin reports. Logs are kept even after key deletion."""
        from datetime import date, datetime, timedelta

        today = _utcnow().date()
        period = (period or "day").lower()

        if period == "day":
            target = date.fromisoformat(day) if day else today
            start = datetime(target.year, target.month, target.day, tzinfo=timezone.utc)
            end = start + timedelta(days=1)
            bucket_expr = "substr(created_at, 1, 10)"
        elif period == "week":
            # ISO week starting Monday
            target = date.fromisoformat(day) if day else today
            start_date = target - timedelta(days=target.weekday())
            start = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
            end = start + timedelta(days=7)
            bucket_expr = "substr(created_at, 1, 10)"
        elif period == "month":
            if day:
                target = date.fromisoformat(day)
            else:
                target = today
            start = datetime(target.year, target.month, 1, tzinfo=timezone.utc)
            if target.month == 12:
                end = datetime(target.year + 1, 1, 1, tzinfo=timezone.utc)
            else:
                end = datetime(target.year, target.month + 1, 1, tzinfo=timezone.utc)
            bucket_expr = "substr(created_at, 1, 10)"
        elif period == "custom":
            if not date_from or not date_to:
                raise ValueError("custom period requires date_from and date_to (YYYY-MM-DD)")
            start_d = date.fromisoformat(date_from)
            end_d = date.fromisoformat(date_to)
            if end_d < start_d:
                start_d, end_d = end_d, start_d
            start = datetime(start_d.year, start_d.month, start_d.day, tzinfo=timezone.utc)
            end = datetime(end_d.year, end_d.month, end_d.day, tzinfo=timezone.utc) + timedelta(days=1)
            bucket_expr = "substr(created_at, 1, 10)"
        else:
            raise ValueError("period must be day, week, month, or custom")

        start_iso = start.isoformat()
        end_iso = end.isoformat()

        with self._lock:
            with self._connect() as conn:
                totals = conn.execute(
                    """
                    SELECT
                        COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                        COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                        COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
                        COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
                        COALESCE(SUM(total_tokens), 0) AS total_tokens,
                        COUNT(*) AS request_count
                    FROM usage_logs
                    WHERE created_at >= ? AND created_at < ?
                    """,
                    (start_iso, end_iso),
                ).fetchone()

                buckets_rows = conn.execute(
                    f"""
                    SELECT
                        {bucket_expr} AS label,
                        COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                        COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                        COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
                        COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
                        COALESCE(SUM(total_tokens), 0) AS total_tokens,
                        COUNT(*) AS request_count
                    FROM usage_logs
                    WHERE created_at >= ? AND created_at < ?
                    GROUP BY label
                    ORDER BY label ASC
                    """,
                    (start_iso, end_iso),
                ).fetchall()

                by_key_rows = conn.execute(
                    """
                    SELECT
                        u.key_id AS key_id,
                        COALESCE(
                            NULLIF(MAX(u.key_name), ''),
                            MAX(k.name),
                            u.key_id
                        ) AS key_name,
                        COALESCE(SUM(u.prompt_tokens), 0) AS prompt_tokens,
                        COALESCE(SUM(u.completion_tokens), 0) AS completion_tokens,
                        COALESCE(SUM(u.cache_read_tokens), 0) AS cache_read_tokens,
                        COALESCE(SUM(u.cache_write_tokens), 0) AS cache_write_tokens,
                        COALESCE(SUM(u.total_tokens), 0) AS total_tokens,
                        COUNT(*) AS request_count,
                        CASE WHEN MAX(k.key_id) IS NULL THEN 1 ELSE 0 END AS key_deleted
                    FROM usage_logs u
                    LEFT JOIN api_keys k ON k.key_id = u.key_id
                    WHERE u.created_at >= ? AND u.created_at < ?
                    GROUP BY u.key_id
                    ORDER BY total_tokens DESC
                    """,
                    (start_iso, end_iso),
                ).fetchall()

        buckets = [
            UsageBucket(
                label=row["label"],
                prompt_tokens=int(row["prompt_tokens"]),
                completion_tokens=int(row["completion_tokens"]),
                cache_read_tokens=int(row["cache_read_tokens"]),
                cache_write_tokens=int(row["cache_write_tokens"]),
                total_tokens=int(row["total_tokens"]),
                request_count=int(row["request_count"]),
            )
            for row in buckets_rows
        ]
        by_key = [
            UsageByKey(
                key_id=row["key_id"],
                key_name=row["key_name"] or row["key_id"],
                prompt_tokens=int(row["prompt_tokens"]),
                completion_tokens=int(row["completion_tokens"]),
                cache_read_tokens=int(row["cache_read_tokens"]),
                cache_write_tokens=int(row["cache_write_tokens"]),
                total_tokens=int(row["total_tokens"]),
                request_count=int(row["request_count"]),
                key_deleted=bool(row["key_deleted"]),
            )
            for row in by_key_rows
        ]
        return {
            "period": period,
            "date_from": start.date().isoformat(),
            "date_to": (end.date() - timedelta(days=1)).isoformat(),
            "prompt_tokens": int(totals["prompt_tokens"]),
            "completion_tokens": int(totals["completion_tokens"]),
            "cache_read_tokens": int(totals["cache_read_tokens"]),
            "cache_write_tokens": int(totals["cache_write_tokens"]),
            "total_tokens": int(totals["total_tokens"]),
            "request_count": int(totals["request_count"]),
            "buckets": buckets,
            "by_key": by_key,
        }

    # --- Admin sessions ---

    def create_admin_session(self, hours: int = 12) -> tuple[str, str]:
        from datetime import timedelta

        token = secrets.token_urlsafe(32)
        created = _utcnow()
        expires = created + timedelta(hours=hours)
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO admin_sessions (token_hash, created_at, expires_at) VALUES (?, ?, ?)",
                    (hash_secret(token), created.isoformat(), expires.isoformat()),
                )
                conn.commit()
        return token, expires.isoformat()

    def validate_admin_session(self, token: str) -> bool:
        if not token:
            return False
        now = _utcnow().isoformat()
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT 1 FROM admin_sessions
                    WHERE token_hash = ? AND expires_at > ?
                    """,
                    (hash_secret(token), now),
                ).fetchone()
        return row is not None

    def revoke_admin_session(self, token: str) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "DELETE FROM admin_sessions WHERE token_hash = ?",
                    (hash_secret(token),),
                )
                conn.commit()

    def revoke_all_admin_sessions(self) -> int:
        """Invalidate every admin browser session (forces re-login)."""
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute("DELETE FROM admin_sessions")
                conn.commit()
                return int(cur.rowcount or 0)

    # --- CDK codes ---

    @staticmethod
    def _generate_cdk_code() -> str:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        parts = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3)]
        return f"CDK-{parts[0]}-{parts[1]}-{parts[2]}"

    def _row_to_cdk(self, row: sqlite3.Row) -> CdkRecord:
        keys = row.keys()
        return CdkRecord(
            code=row["code"],
            label=row["label"],
            rpm_limit=row["rpm_limit"],
            monthly_token_quota=row["monthly_token_quota"],
            created_at=row["created_at"],
            redeemed_at=row["redeemed_at"],
            key_id=row["key_id"],
            revoked=bool(row["revoked"]),
            allowed_models=row["allowed_models"] if "allowed_models" in keys else "",
        )

    def create_cdks(
        self,
        count: int,
        label: str,
        rpm_limit: int | None = None,
        monthly_token_quota: int | None = None,
        allowed_models: list[str] | str | None = None,
    ) -> list[CdkRecord]:
        count = max(1, min(int(count), 1000))
        rpm = rpm_limit if rpm_limit is not None else DEFAULT_RPM_LIMIT
        quota = monthly_token_quota if monthly_token_quota is not None else DEFAULT_MONTHLY_TOKEN_QUOTA
        models = normalize_allowed_models(allowed_models)
        now = _utcnow().isoformat()
        created: list[CdkRecord] = []
        with self._lock:
            with self._connect() as conn:
                for _ in range(count):
                    for _attempt in range(20):
                        code = self._generate_cdk_code()
                        try:
                            conn.execute(
                                """
                                INSERT INTO cdks (
                                    code, label, rpm_limit, monthly_token_quota,
                                    created_at, redeemed_at, key_id, revoked, allowed_models
                                ) VALUES (?, ?, ?, ?, ?, NULL, NULL, 0, ?)
                                """,
                                (code, label, rpm, quota, now, models),
                            )
                            created.append(
                                CdkRecord(
                                    code=code,
                                    label=label,
                                    rpm_limit=rpm,
                                    monthly_token_quota=quota,
                                    created_at=now,
                                    redeemed_at=None,
                                    key_id=None,
                                    revoked=False,
                                    allowed_models=models,
                                )
                            )
                            break
                        except sqlite3.IntegrityError:
                            continue
                    else:
                        raise RuntimeError("Unable to generate unique CDK code")
                conn.commit()
        return created

    def list_cdks(self, include_redeemed: bool = True) -> list[CdkRecord]:
        with self._lock:
            with self._connect() as conn:
                if include_redeemed:
                    rows = conn.execute("SELECT * FROM cdks ORDER BY created_at DESC").fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT * FROM cdks
                        WHERE redeemed_at IS NULL AND revoked = 0
                        ORDER BY created_at DESC
                        """
                    ).fetchall()
        return [self._row_to_cdk(r) for r in rows]

    def revoke_cdk(self, code: str) -> CdkRecord | None:
        with self._lock:
            with self._connect() as conn:
                conn.execute("UPDATE cdks SET revoked = 1 WHERE code = ?", (code.upper(),))
                conn.commit()
                row = conn.execute("SELECT * FROM cdks WHERE code = ?", (code.upper(),)).fetchone()
        return self._row_to_cdk(row) if row else None

    def delete_cdk(self, code: str) -> CdkRecord | None:
        """Permanently remove a CDK record."""
        normalized = code.strip().upper()
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM cdks WHERE code = ?", (normalized,)).fetchone()
                if not row:
                    return None
                record = self._row_to_cdk(row)
                conn.execute("DELETE FROM cdks WHERE code = ?", (normalized,))
                conn.commit()
        return record

    def redeem_cdk(self, code: str) -> tuple[CdkRecord, ApiKeyRecord, str]:
        normalized = code.strip().upper()
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM cdks WHERE code = ?", (normalized,)).fetchone()
                if not row:
                    raise KeyError("CDK not found")
                cdk = self._row_to_cdk(row)
                if cdk.revoked:
                    raise PermissionError("CDK has been revoked")
                if cdk.redeemed_at:
                    raise PermissionError("CDK already redeemed")

                # Create key inside same lock; create_key also locks — avoid deadlock by inlining insert
                key_id = secrets.token_hex(8)
                secret = secrets.token_urlsafe(32)
                plaintext = f"bag_{key_id}_{secret}"
                now = _utcnow().isoformat()
                name = f"{cdk.label}-{key_id[:6]}"
                conn.execute(
                    """
                    INSERT INTO api_keys (
                        key_id, name, secret_hash, rpm_limit, monthly_token_quota,
                        revoked, created_at, last_used_at, usage_month,
                        prompt_tokens_month, completion_tokens_month, request_count_month,
                        allowed_models
                    ) VALUES (?, ?, ?, ?, ?, 0, ?, NULL, ?, 0, 0, 0, ?)
                    """,
                    (
                        key_id,
                        name,
                        hash_secret(secret),
                        cdk.rpm_limit,
                        cdk.monthly_token_quota,
                        now,
                        _month_key(),
                        cdk.allowed_models,
                    ),
                )
                cur = conn.execute(
                    """
                    UPDATE cdks
                    SET redeemed_at = ?, key_id = ?
                    WHERE code = ? AND redeemed_at IS NULL AND revoked = 0
                    """,
                    (now, key_id, normalized),
                )
                if cur.rowcount == 0:
                    raise PermissionError("CDK already redeemed")
                conn.commit()
                key_row = conn.execute("SELECT * FROM api_keys WHERE key_id = ?", (key_id,)).fetchone()
                cdk_row = conn.execute("SELECT * FROM cdks WHERE code = ?", (normalized,)).fetchone()
        return self._row_to_cdk(cdk_row), self._row_to_record(key_row), plaintext

    # --- AWS credentials pool ---

    def _row_to_aws_credential(self, row: sqlite3.Row) -> AwsCredentialRecord:
        keys = row.keys()
        return AwsCredentialRecord(
            cred_id=row["cred_id"],
            name=row["name"],
            access_key_id=row["access_key_id"],
            secret_access_key=row["secret_access_key"],
            session_token=row["session_token"] or "",
            region=row["region"] or "",
            allowed_models=row["allowed_models"] or "",
            priority=int(row["priority"] or 100),
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
            last_used_at=row["last_used_at"],
            is_default=bool(row["is_default"]) if "is_default" in keys else False,
            usage_month=row["usage_month"] if "usage_month" in keys else "",
            prompt_tokens_month=int(row["prompt_tokens_month"] or 0) if "prompt_tokens_month" in keys else 0,
            completion_tokens_month=int(row["completion_tokens_month"] or 0)
            if "completion_tokens_month" in keys
            else 0,
            request_count_month=int(row["request_count_month"] or 0) if "request_count_month" in keys else 0,
        )

    def list_aws_credentials(self, include_disabled: bool = True) -> list[AwsCredentialRecord]:
        with self._lock:
            with self._connect() as conn:
                if include_disabled:
                    rows = conn.execute(
                        """
                        SELECT * FROM aws_credentials
                        ORDER BY is_default DESC, priority ASC, created_at ASC
                        """
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT * FROM aws_credentials
                        WHERE enabled = 1
                        ORDER BY is_default DESC, priority ASC, created_at ASC
                        """
                    ).fetchall()
        return [self._row_to_aws_credential(r) for r in rows]

    def get_aws_credential(self, cred_id: str) -> AwsCredentialRecord | None:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM aws_credentials WHERE cred_id = ?",
                    (cred_id,),
                ).fetchone()
        return self._row_to_aws_credential(row) if row else None

    def create_aws_credential(
        self,
        *,
        name: str,
        access_key_id: str,
        secret_access_key: str,
        session_token: str = "",
        region: str = "",
        allowed_models: list[str] | str | None = None,
        priority: int = 100,
        enabled: bool = True,
    ) -> AwsCredentialRecord:
        cred_id = secrets.token_hex(8)
        now = _utcnow().isoformat()
        with self._lock:
            with self._connect() as conn:
                has_default = conn.execute(
                    "SELECT 1 FROM aws_credentials WHERE is_default = 1 LIMIT 1"
                ).fetchone()
                make_default = not bool(has_default)
                record = AwsCredentialRecord(
                    cred_id=cred_id,
                    name=(name or "aws").strip() or "aws",
                    access_key_id=access_key_id.strip(),
                    secret_access_key=secret_access_key.strip(),
                    session_token=(session_token or "").strip(),
                    region=(region or "").strip(),
                    allowed_models=normalize_allowed_models(allowed_models),
                    priority=int(priority if priority is not None else 100),
                    enabled=bool(enabled),
                    created_at=now,
                    last_used_at=None,
                    is_default=make_default,
                    usage_month=_month_key(),
                )
                if not record.access_key_id or not record.secret_access_key:
                    raise ValueError("access_key_id and secret_access_key are required")
                conn.execute(
                    """
                    INSERT INTO aws_credentials (
                        cred_id, name, access_key_id, secret_access_key, session_token,
                        region, allowed_models, priority, enabled, created_at, last_used_at,
                        is_default, usage_month, prompt_tokens_month, completion_tokens_month,
                        request_count_month
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0)
                    """,
                    (
                        record.cred_id,
                        record.name,
                        record.access_key_id,
                        record.secret_access_key,
                        record.session_token,
                        record.region,
                        record.allowed_models,
                        record.priority,
                        1 if record.enabled else 0,
                        record.created_at,
                        None,
                        1 if make_default else 0,
                        record.usage_month,
                    ),
                )
                conn.commit()
        return record

    def update_aws_credential(
        self,
        cred_id: str,
        *,
        name: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        session_token: str | None = None,
        region: str | None = None,
        allowed_models: list[str] | str | None = None,
        priority: int | None = None,
        enabled: bool | None = None,
    ) -> AwsCredentialRecord | None:
        record = self.get_aws_credential(cred_id)
        if not record:
            return None
        updated = AwsCredentialRecord(
            cred_id=record.cred_id,
            name=(name.strip() if name is not None else record.name) or record.name,
            access_key_id=(access_key_id.strip() if access_key_id is not None else record.access_key_id),
            secret_access_key=(
                secret_access_key.strip() if secret_access_key is not None else record.secret_access_key
            ),
            session_token=(
                session_token.strip() if session_token is not None else record.session_token
            ),
            region=(region.strip() if region is not None else record.region),
            allowed_models=(
                normalize_allowed_models(allowed_models)
                if allowed_models is not None
                else record.allowed_models
            ),
            priority=int(priority) if priority is not None else record.priority,
            enabled=bool(enabled) if enabled is not None else record.enabled,
            created_at=record.created_at,
            last_used_at=record.last_used_at,
            is_default=record.is_default,
            usage_month=record.usage_month,
            prompt_tokens_month=record.prompt_tokens_month,
            completion_tokens_month=record.completion_tokens_month,
            request_count_month=record.request_count_month,
        )
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE aws_credentials
                    SET name = ?, access_key_id = ?, secret_access_key = ?, session_token = ?,
                        region = ?, allowed_models = ?, priority = ?, enabled = ?
                    WHERE cred_id = ?
                    """,
                    (
                        updated.name,
                        updated.access_key_id,
                        updated.secret_access_key,
                        updated.session_token,
                        updated.region,
                        updated.allowed_models,
                        updated.priority,
                        1 if updated.enabled else 0,
                        cred_id,
                    ),
                )
                conn.commit()
        return updated

    def delete_aws_credential(self, cred_id: str) -> AwsCredentialRecord | None:
        record = self.get_aws_credential(cred_id)
        if not record:
            return None
        with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM aws_credentials WHERE cred_id = ?", (cred_id,))
                if record.is_default:
                    nxt = conn.execute(
                        """
                        SELECT cred_id FROM aws_credentials
                        WHERE enabled = 1
                        ORDER BY priority ASC, created_at ASC
                        LIMIT 1
                        """
                    ).fetchone()
                    if nxt:
                        conn.execute(
                            "UPDATE aws_credentials SET is_default = 1 WHERE cred_id = ?",
                            (nxt["cred_id"],),
                        )
                conn.commit()
        return record

    def set_aws_credential_enabled(self, cred_id: str, enabled: bool) -> AwsCredentialRecord | None:
        return self.update_aws_credential(cred_id, enabled=enabled)

    def touch_aws_credential(self, cred_id: str) -> None:
        now = _utcnow().isoformat()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE aws_credentials SET last_used_at = ? WHERE cred_id = ?",
                    (now, cred_id),
                )
                conn.commit()

    def select_aws_credentials_for_model(self, model: str) -> list[AwsCredentialRecord]:
        """Return enabled AWS keys for this model.

        Routing rule:
        - If any key **explicitly** lists the model (e.g. Fable 5), ONLY those keys are used.
          Wildcard / empty-allowlist keys are skipped.
        - Otherwise prefer the marked default key, then other wildcard keys.
        """
        model = (model or "").strip()
        enabled = self.list_aws_credentials(include_disabled=False)
        explicit = [c for c in enabled if c.explicitly_allows_model(model)]
        wildcard = [c for c in enabled if not c.allowed_models_list]
        # Also allow the default key when it has a specific allowlist that includes this model
        # (already in explicit). For non-explicit models, use default first among wildcards,
        # or the default key if it is the only general fallback.
        if explicit:
            pool = explicit
        else:
            defaults = [c for c in enabled if c.is_default]
            pool = defaults + [c for c in wildcard if not c.is_default]
            if not pool:
                pool = wildcard
        if not pool:
            return []

        def sort_key(c: AwsCredentialRecord) -> tuple:
            last = c.last_used_at or ""
            # Within a pool, default first, then priority.
            return (0 if c.is_default else 1, c.priority, last, c.created_at)

        pool.sort(key=sort_key)
        return pool

    def set_default_aws_credential(self, cred_id: str) -> AwsCredentialRecord | None:
        record = self.get_aws_credential(cred_id)
        if not record:
            return None
        with self._lock:
            with self._connect() as conn:
                conn.execute("UPDATE aws_credentials SET is_default = 0")
                conn.execute(
                    "UPDATE aws_credentials SET is_default = 1 WHERE cred_id = ?",
                    (cred_id,),
                )
                conn.commit()
        return self.get_aws_credential(cred_id)

    def aws_usage_by_model(self, cred_id: str, *, limit: int = 20) -> list[dict]:
        """Token totals per model for one AWS key (current calendar month, UTC)."""
        month = _month_key()
        start = f"{month}-01T00:00:00"
        # Next month prefix bound
        y, m = int(month[:4]), int(month[5:7])
        if m == 12:
            end = f"{y + 1}-01-01T00:00:00"
        else:
            end = f"{y}-{m + 1:02d}-01T00:00:00"
        limit = max(1, min(int(limit), 100))
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT model,
                           SUM(prompt_tokens) AS prompt_tokens,
                           SUM(completion_tokens) AS completion_tokens,
                           SUM(total_tokens) AS total_tokens,
                           COUNT(*) AS request_count
                    FROM usage_logs
                    WHERE aws_cred_id = ?
                      AND created_at >= ?
                      AND created_at < ?
                    GROUP BY model
                    ORDER BY total_tokens DESC
                    LIMIT ?
                    """,
                    (cred_id, start, end, limit),
                ).fetchall()
        return [
            {
                "model": row["model"] or "—",
                "prompt_tokens": int(row["prompt_tokens"] or 0),
                "completion_tokens": int(row["completion_tokens"] or 0),
                "total_tokens": int(row["total_tokens"] or 0),
                "request_count": int(row["request_count"] or 0),
            }
            for row in rows
        ]

    def insert_request_log(
        self,
        *,
        method: str,
        path: str,
        status_code: int,
        client_ip: str = "",
        latency_ms: int = 0,
        key_id: str = "",
        error: str = "",
        user_agent: str = "",
    ) -> None:
        now = _utcnow().isoformat()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO request_logs (
                        created_at, method, path, status_code, client_ip,
                        latency_ms, key_id, error, user_agent
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        now,
                        (method or "")[:16],
                        (path or "")[:512],
                        int(status_code or 0),
                        (client_ip or "")[:128],
                        max(0, int(latency_ms or 0)),
                        (key_id or "")[:64],
                        (error or "")[:512],
                        (user_agent or "")[:256],
                    ),
                )
                # Occasional prune so spam floods cannot grow the DB forever.
                row_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
                if row_id % 200 == 0:
                    cutoff = (_utcnow() - timedelta(days=14)).isoformat()
                    conn.execute(
                        """
                        DELETE FROM request_logs
                        WHERE id < (SELECT COALESCE(MAX(id), 0) - 80000 FROM request_logs)
                           OR created_at < ?
                        """,
                        (cutoff,),
                    )
                conn.commit()

    @staticmethod
    def _request_log_filters(
        *,
        ip: str | None = None,
        method: str | None = None,
        status_min: int | None = None,
        status_max: int | None = None,
        path_contains: str | None = None,
        errors_only: bool = False,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> tuple[str, list]:
        clauses: list[str] = []
        params: list = []
        if ip:
            clauses.append("client_ip LIKE ?")
            params.append(f"%{ip.strip()}%")
        if method:
            clauses.append("method = ?")
            params.append(method.strip().upper())
        if status_min is not None:
            clauses.append("status_code >= ?")
            params.append(int(status_min))
        if status_max is not None:
            clauses.append("status_code <= ?")
            params.append(int(status_max))
        if path_contains:
            clauses.append("path LIKE ?")
            params.append(f"%{path_contains.strip()}%")
        if errors_only:
            clauses.append("status_code >= 400")
        if date_from:
            clauses.append("created_at >= ?")
            params.append(date_from.strip()[:10] + "T00:00:00")
        if date_to:
            clauses.append("created_at < ?")
            # Inclusive end-day: next midnight
            params.append(date_to.strip()[:10] + "T23:59:59.999999")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params

    def list_request_logs(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        ip: str | None = None,
        method: str | None = None,
        status_min: int | None = None,
        status_max: int | None = None,
        path_contains: str | None = None,
        errors_only: bool = False,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[RequestLogRecord]:
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))
        where, params = self._request_log_filters(
            ip=ip,
            method=method,
            status_min=status_min,
            status_max=status_max,
            path_contains=path_contains,
            errors_only=errors_only,
            date_from=date_from,
            date_to=date_to,
        )
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT * FROM request_logs
                    {where}
                    ORDER BY created_at DESC, id DESC
                    LIMIT ? OFFSET ?
                    """,
                    (*params, limit, offset),
                ).fetchall()
        return [self._row_to_request_log(row) for row in rows]

    def count_request_logs(
        self,
        *,
        ip: str | None = None,
        method: str | None = None,
        status_min: int | None = None,
        status_max: int | None = None,
        path_contains: str | None = None,
        errors_only: bool = False,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> int:
        where, params = self._request_log_filters(
            ip=ip,
            method=method,
            status_min=status_min,
            status_max=status_max,
            path_contains=path_contains,
            errors_only=errors_only,
            date_from=date_from,
            date_to=date_to,
        )
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    f"SELECT COUNT(*) AS count FROM request_logs{where}",
                    params,
                ).fetchone()
        return int(row["count"]) if row else 0

    def request_log_ip_summary(self, *, hours: int = 24, limit: int = 30) -> list[RequestLogIpSummary]:
        hours = max(1, min(int(hours), 168))
        limit = max(1, min(int(limit), 100))
        cutoff = (_utcnow() - timedelta(hours=hours)).isoformat()
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT
                        client_ip,
                        COUNT(*) AS request_count,
                        SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END) AS error_count,
                        MAX(created_at) AS last_seen
                    FROM request_logs
                    WHERE created_at >= ?
                      AND client_ip != ''
                    GROUP BY client_ip
                    ORDER BY request_count DESC, error_count DESC
                    LIMIT ?
                    """,
                    (cutoff, limit),
                ).fetchall()
        return [
            RequestLogIpSummary(
                client_ip=row["client_ip"],
                request_count=int(row["request_count"] or 0),
                error_count=int(row["error_count"] or 0),
                last_seen=row["last_seen"] or "",
            )
            for row in rows
        ]

    def _row_to_request_log(self, row: sqlite3.Row) -> RequestLogRecord:
        return RequestLogRecord(
            id=row["id"],
            created_at=row["created_at"],
            method=row["method"],
            path=row["path"],
            status_code=int(row["status_code"] or 0),
            client_ip=row["client_ip"] or "",
            latency_ms=int(row["latency_ms"] or 0),
            key_id=row["key_id"] or "",
            error=row["error"] or "",
            user_agent=row["user_agent"] or "",
        )

    @staticmethod
    def _normalize_ip(ip: str) -> str:
        return (ip or "").strip()[:128]

    def is_ip_banned(self, ip: str) -> bool:
        norm = self._normalize_ip(ip)
        if not norm:
            return False
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT 1 FROM banned_ips WHERE ip = ?", (norm,)).fetchone()
                return bool(row)

    def list_banned_ips(self) -> list[BannedIpRecord]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM banned_ips ORDER BY created_at DESC"
                ).fetchall()
        return [self._row_to_banned_ip(r) for r in rows]

    def ban_ip(self, ip: str, *, reason: str = "", source: str = "manual") -> BannedIpRecord:
        norm = self._normalize_ip(ip)
        if not norm or norm == "unknown":
            raise ValueError("Invalid IP to ban")
        if norm in ("127.0.0.1", "::1", "localhost"):
            raise ValueError("Cannot ban localhost")
        now = _utcnow().isoformat()
        with self._lock:
            with self._connect() as conn:
                existing = conn.execute("SELECT * FROM banned_ips WHERE ip = ?", (norm,)).fetchone()
                if existing:
                    conn.execute(
                        """
                        UPDATE banned_ips
                        SET reason = ?, source = ?
                        WHERE ip = ?
                        """,
                        ((reason or "")[:256], (source or "manual")[:64], norm),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO banned_ips (ip, reason, source, created_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (norm, (reason or "")[:256], (source or "manual")[:64], now),
                    )
                row = conn.execute("SELECT * FROM banned_ips WHERE ip = ?", (norm,)).fetchone()
        return self._row_to_banned_ip(row)

    def unban_ip(self, ip: str) -> BannedIpRecord | None:
        norm = self._normalize_ip(ip)
        if not norm:
            return None
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM banned_ips WHERE ip = ?", (norm,)).fetchone()
                if not row:
                    return None
                conn.execute("DELETE FROM banned_ips WHERE ip = ?", (norm,))
                conn.execute("DELETE FROM admin_login_failures WHERE ip = ?", (norm,))
        return self._row_to_banned_ip(row)

    def record_admin_login_failure(self, ip: str, *, ban_after: int = 10) -> tuple[int, bool]:
        """Increment failed admin logins for IP. Returns (fail_count, newly_banned)."""
        norm = self._normalize_ip(ip)
        if not norm or norm in ("127.0.0.1", "::1", "localhost", "unknown"):
            return 0, False
        ban_after = max(1, int(ban_after))
        now = _utcnow().isoformat()
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT fail_count FROM admin_login_failures WHERE ip = ?",
                    (norm,),
                ).fetchone()
                count = int(row["fail_count"] if row else 0) + 1
                conn.execute(
                    """
                    INSERT INTO admin_login_failures (ip, fail_count, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(ip) DO UPDATE SET
                        fail_count = excluded.fail_count,
                        updated_at = excluded.updated_at
                    """,
                    (norm, count, now),
                )
                if count < ban_after:
                    return count, False
                if conn.execute("SELECT 1 FROM banned_ips WHERE ip = ?", (norm,)).fetchone():
                    return count, False
                conn.execute(
                    """
                    INSERT INTO banned_ips (ip, reason, source, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        norm,
                        f"Sai mật khẩu admin {count} lần",
                        "login_failures",
                        now,
                    ),
                )
                return count, True

    def clear_admin_login_failures(self, ip: str) -> None:
        norm = self._normalize_ip(ip)
        if not norm:
            return
        with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM admin_login_failures WHERE ip = ?", (norm,))

    def _row_to_banned_ip(self, row: sqlite3.Row) -> BannedIpRecord:
        return BannedIpRecord(
            ip=row["ip"] or "",
            reason=row["reason"] or "",
            source=row["source"] or "",
            created_at=row["created_at"] or "",
        )

    def get_setting(self, key: str, default: str = "") -> str:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT value FROM admin_settings WHERE key = ?",
                    (key,),
                ).fetchone()
        return (row["value"] if row else default) or default

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO admin_settings (key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (key, value or ""),
                )

    def admin_2fa_enabled(self) -> bool:
        return bool(self.get_setting("admin_2fa_totp_secret") or self.get_setting("admin_2fa_pin_hash"))

    def get_admin_totp_secret(self) -> str:
        return (self.get_setting("admin_2fa_totp_secret") or "").strip()

    def set_admin_totp_secret(self, secret: str) -> None:
        clean = "".join((secret or "").split()).upper().rstrip("=")
        if len(clean) < 16:
            raise ValueError("Invalid TOTP secret")
        self.set_setting("admin_2fa_totp_secret", clean)
        # Clear legacy static PIN so only TOTP is used.
        self.set_setting("admin_2fa_pin_hash", "")
        self.set_setting("admin_2fa_pin_salt", "")
        self.set_setting("admin_2fa_updated_at", _utcnow().isoformat())

    def verify_admin_2fa_pin(self, pin: str) -> bool:
        """Verify authenticator TOTP (preferred) or legacy static 6-digit PIN."""
        from api.security import verify_totp

        secret = self.get_admin_totp_secret()
        if secret:
            return verify_totp(secret, pin)
        # Legacy static PIN (hash) — kept until regenerated to TOTP.
        clean = (pin or "").strip()
        expected = self.get_setting("admin_2fa_pin_hash")
        if not expected:
            return True
        if not (len(clean) == 6 and clean.isdigit()):
            return False
        salt = self.get_setting("admin_2fa_pin_salt")
        digest = hashlib.sha256(f"{salt}:{clean}".encode("utf-8")).hexdigest()
        return secrets.compare_digest(digest.lower(), expected.strip().lower())

    def generate_admin_totp_secret(self) -> str:
        """Create a new TOTP secret, store it, return plaintext once for authenticator setup."""
        from api.security import generate_totp_secret

        secret = generate_totp_secret(nbytes=20)
        self.set_admin_totp_secret(secret)
        return secret

    # Back-compat alias used by older tests/call sites.
    def generate_admin_2fa_pin(self, *, salt: str = "") -> str:
        _ = salt
        return self.generate_admin_totp_secret()

    def insert_admin_login_log(
        self,
        *,
        client_ip: str,
        success: bool,
        detail: str = "",
        user_agent: str = "",
    ) -> None:
        now = _utcnow().isoformat()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO admin_login_logs (
                        created_at, client_ip, success, detail, user_agent
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        now,
                        (client_ip or "")[:128],
                        1 if success else 0,
                        (detail or "")[:256],
                        (user_agent or "")[:256],
                    ),
                )
                conn.execute(
                    """
                    DELETE FROM admin_login_logs
                    WHERE id < (SELECT COALESCE(MAX(id), 0) - 20000 FROM admin_login_logs)
                    """
                )

    def list_admin_login_logs(self, *, limit: int = 100, offset: int = 0) -> list[AdminLoginLogRecord]:
        safe_limit = max(1, min(int(limit), 500))
        safe_offset = max(0, int(offset))
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM admin_login_logs
                    ORDER BY id DESC
                    LIMIT ? OFFSET ?
                    """,
                    (safe_limit, safe_offset),
                ).fetchall()
        return [
            AdminLoginLogRecord(
                id=int(row["id"]),
                created_at=row["created_at"] or "",
                client_ip=row["client_ip"] or "",
                success=bool(row["success"]),
                detail=row["detail"] or "",
                user_agent=row["user_agent"] or "",
            )
            for row in rows
        ]

    def count_admin_login_logs(self) -> int:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT COUNT(*) AS c FROM admin_login_logs").fetchone()
        return int(row["c"] if row else 0)

    def migrate_legacy_allowlists_to_tiers(self) -> dict[str, int]:
        """Rewrite Bedrock-style allowlists to short tier markers (4.6 / 4.8 / fable5)."""
        from api.model_alias import infer_tier_ceiling

        updated_keys = 0
        updated_cdks = 0
        with self._lock:
            with self._connect() as conn:
                for table, counter_name in (("api_keys", "keys"), ("cdks", "cdks")):
                    rows = conn.execute(f"SELECT rowid, allowed_models FROM {table}").fetchall()
                    for row in rows:
                        raw = row["allowed_models"] or ""
                        items = parse_allowed_models(raw)
                        if not items:
                            continue
                        tier = infer_tier_ceiling(items)
                        if not tier:
                            continue
                        # Already a single canonical short tier — skip.
                        if len(items) == 1 and items[0] == tier:
                            continue
                        if raw == tier:
                            continue
                        conn.execute(
                            f"UPDATE {table} SET allowed_models = ? WHERE rowid = ?",
                            (tier, row["rowid"]),
                        )
                        if counter_name == "keys":
                            updated_keys += 1
                        else:
                            updated_cdks += 1
                conn.commit()
        return {"keys": updated_keys, "cdks": updated_cdks}


class RateLimitError(Exception):
    pass


class QuotaExceededError(Exception):
    pass


# Process-wide singleton; tests can replace this.
auth_db = AuthDatabase()

# Dedicated writer so request logging never blocks the asyncio event loop / thread pool.
_request_log_queue: queue.Queue = queue.Queue(maxsize=8000)
_request_log_writer_started = False
_request_log_writer_lock = threading.Lock()


def enqueue_request_log(**kwargs) -> None:
    """Non-blocking enqueue for HTTP access logs (drops oldest pressure via Full)."""
    global _request_log_writer_started
    try:
        _request_log_queue.put_nowait(kwargs)
    except queue.Full:
        try:
            _request_log_queue.get_nowait()
        except queue.Empty:
            pass
        try:
            _request_log_queue.put_nowait(kwargs)
        except queue.Full:
            return
    if not _request_log_writer_started:
        with _request_log_writer_lock:
            if not _request_log_writer_started:
                t = threading.Thread(target=_request_log_writer_loop, name="request-log-writer", daemon=True)
                t.start()
                _request_log_writer_started = True


def _request_log_writer_loop() -> None:
    while True:
        item = _request_log_queue.get()
        if item is None:
            break
        try:
            auth_db.insert_request_log(**item)
        except Exception as exc:  # noqa: BLE001
            _log.debug("request log writer failed: %s", exc)

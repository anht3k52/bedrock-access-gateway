"""Password hashing, admin login brute-force protection, TOTP 2FA, and IP ban cache."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import threading
import time
import urllib.parse
from collections import defaultdict

_banned_ips_cache: set[str] = set()
_banned_ips_lock = threading.Lock()
_banned_ips_loaded = False


def refresh_banned_ips_cache() -> set[str]:
    """Reload banned IP set from SQLite into process memory."""
    global _banned_ips_loaded
    from api.db import auth_db

    ips = {r.ip for r in auth_db.list_banned_ips() if r.ip}
    with _banned_ips_lock:
        _banned_ips_cache.clear()
        _banned_ips_cache.update(ips)
        _banned_ips_loaded = True
        return set(_banned_ips_cache)


def is_ip_banned(ip: str) -> bool:
    norm = (ip or "").strip()
    if not norm:
        return False
    if not _banned_ips_loaded:
        refresh_banned_ips_cache()
    with _banned_ips_lock:
        return norm in _banned_ips_cache


def mark_ip_banned(ip: str) -> None:
    norm = (ip or "").strip()
    if not norm:
        return
    with _banned_ips_lock:
        global _banned_ips_loaded
        _banned_ips_cache.add(norm)
        _banned_ips_loaded = True


def mark_ip_unbanned(ip: str) -> None:
    norm = (ip or "").strip()
    if not norm:
        return
    with _banned_ips_lock:
        _banned_ips_cache.discard(norm)


def hash_password_sha256(password: str, salt: str = "") -> str:
    payload = f"{salt}:{password}" if salt else password
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_password_sha256(
    password: str,
    expected_hex: str | None,
    *,
    salt: str = "",
    plaintext_fallback: str | None = None,
) -> bool:
    """Constant-time password check. Prefer SHA-256 hash; optional plaintext fallback for tests."""
    if expected_hex:
        digest = hash_password_sha256(password, salt)
        return secrets.compare_digest(digest.lower(), expected_hex.strip().lower())
    if plaintext_fallback is not None:
        return secrets.compare_digest(password, plaintext_fallback)
    return False


def generate_totp_secret(*, nbytes: int = 20) -> str:
    """Return a base32 secret (no padding) for authenticator apps."""
    raw = secrets.token_bytes(max(10, int(nbytes)))
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def _normalize_totp_secret(secret: str) -> bytes:
    clean = "".join((secret or "").split()).upper()
    # Pad to multiple of 8 for base32 decode.
    pad = (-len(clean)) % 8
    return base64.b32decode(clean + ("=" * pad), casefold=True)


def totp_code(secret: str, *, for_time: float | None = None, step: int = 30, digits: int = 6) -> str:
    """Compute current TOTP code for a base32 secret."""
    counter = int((time.time() if for_time is None else for_time) // step)
    key = _normalize_totp_secret(secret)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    num = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(num % (10**digits)).zfill(digits)


def verify_totp(
    secret: str,
    code: str,
    *,
    window: int = 1,
    step: int = 30,
    digits: int = 6,
) -> bool:
    """Validate a 6-digit TOTP with ±window steps (default ±30s)."""
    clean = (code or "").strip().replace(" ", "")
    if not (len(clean) == digits and clean.isdigit()):
        return False
    if not (secret or "").strip():
        return False
    now = time.time()
    for drift in range(-window, window + 1):
        expected = totp_code(secret, for_time=now + drift * step, step=step, digits=digits)
        if secrets.compare_digest(expected, clean):
            return True
    return False


def totp_provisioning_uri(
    secret: str,
    *,
    account_name: str = "admin",
    issuer: str = "MRDEV Gateway",
) -> str:
    label = urllib.parse.quote(f"{issuer}:{account_name}")
    query = urllib.parse.urlencode(
        {
            "secret": "".join(secret.split()).upper().rstrip("="),
            "issuer": issuer,
            "algorithm": "SHA1",
            "digits": "6",
            "period": "30",
        }
    )
    return f"otpauth://totp/{label}?{query}"


class LoginRateLimiter:
    """In-memory lockout for failed admin logins (per client IP)."""

    def __init__(self, max_failures: int = 5, lockout_seconds: int = 900):
        self.max_failures = max_failures
        self.lockout_seconds = lockout_seconds
        self._lock = threading.Lock()
        self._failures: dict[str, list[float]] = defaultdict(list)
        self._locked_until: dict[str, float] = {}

    def is_blocked(self, client_ip: str) -> tuple[bool, int]:
        now = time.time()
        with self._lock:
            until = self._locked_until.get(client_ip, 0)
            if until > now:
                return True, int(until - now)
            if until and until <= now:
                self._locked_until.pop(client_ip, None)
                self._failures.pop(client_ip, None)
            return False, 0

    def register_failure(self, client_ip: str) -> tuple[bool, int]:
        now = time.time()
        with self._lock:
            window = self._failures[client_ip]
            window.append(now)
            cutoff = now - 3600
            self._failures[client_ip] = [t for t in window if t >= cutoff]
            recent = [t for t in self._failures[client_ip] if now - t <= self.lockout_seconds]
            self._failures[client_ip] = recent
            if len(recent) >= self.max_failures:
                self._locked_until[client_ip] = now + self.lockout_seconds
                return True, self.lockout_seconds
            return False, 0

    def register_success(self, client_ip: str) -> None:
        with self._lock:
            self._failures.pop(client_ip, None)
            self._locked_until.pop(client_ip, None)


admin_login_limiter = LoginRateLimiter(max_failures=5, lockout_seconds=900)

"""Client-safe error messages — never leak upstream provider details."""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# Any of these → replace with a generic client message.
_LEAK_RE = re.compile(
    r"(?i)("
    r"https?://|"
    r"arn:aws:|"
    r"amazonaws\.com|"
    r"bedrock-runtime|"
    r"\bbedrock\b|"
    r"converse-stream|"
    r"\bconverse\b|"
    r"invokemodel|"
    r"endpoint url|"
    r"accessdeniedexception|"
    r"throttlingexception|"
    r"validationexception|"
    r"unrecognizedclientexception|"
    r"servicequotaexceeded|"
    r"us\.anthropic\.|"
    r"eu\.anthropic\.|"
    r"global\.anthropic\.|"
    r"anthropic\.claude-|"
    r"application-inference-profile|"
    r"\bAKIA[0-9A-Z]{16}\b|"
    r"iam::\d{12}|"
    r"security token|"
    r"unable to locate credentials|"
    r"connection was closed|"
    r"could not connect to the endpoint|"
    r"connection broken|"
    r"connectionreset"
    r")"
)

_GENERIC = {
    400: "Invalid request",
    401: "Unauthorized. Please sign in again.",
    403: "Forbidden",
    429: "Rate limited. Try again later.",
    500: "Upstream error. Try again later.",
    502: "Upstream error. Try again later.",
    503: "Service temporarily unavailable",
}

# Product messages we intentionally show to clients (substring match).
_SAFE_PREFIXES = (
    "invalid request",
    "unauthorized",
    "forbidden",
    "rate limited",
    "upstream error",
    "service temporarily",
    "unsupported model",
    "model '",
    "model id",
    "use short",
    "use get /models",
    "api key",
    "invalid api",
    "invalid admin",
    "cdk ",
    "multimodal message",
    "max_tokens",
    "no upstream credentials",
    "please sign in",
    "sai ",
    "quá nhiều",
)


def looks_like_upstream_leak(text: str) -> bool:
    if not text:
        return False
    if _LEAK_RE.search(text):
        return True
    # Starlette HTTPException str(): "500: <detail>"
    if re.match(r"^\d{3}:\s", text.strip()):
        return True
    return False


def client_safe_detail(detail: Any, *, status: int = 500) -> str:
    """Return a message safe to show API clients."""
    fallback = _GENERIC.get(status, _GENERIC[500])
    # Auth errors: always use a clear non-upstream message.
    if status in (401, 403):
        text = str(detail).strip() if detail is not None else ""
        if text and not looks_like_upstream_leak(text) and len(text) <= 280:
            lower = text.lower()
            if any(p in lower for p in ("invalid", "unauthorized", "forbidden", "sai ", "admin", "api key")):
                return text
        return fallback
    if detail is None:
        return fallback
    if isinstance(detail, (list, dict)):
        return fallback
    text = str(detail).strip()
    if not text:
        return fallback
    if looks_like_upstream_leak(text):
        return fallback
    lower = text.lower()
    if any(lower.startswith(p) or p in lower for p in _SAFE_PREFIXES):
        if len(text) > 280:
            return fallback
        return text
    # Unknown free-form text — do not forward (may contain provider internals).
    return fallback


def status_and_detail_for_upstream(exc: BaseException) -> tuple[int, str]:
    """Map an upstream exception to (HTTP status, client-safe detail)."""
    if isinstance(exc, HTTPException):
        code = int(exc.status_code or 500)
        return code, client_safe_detail(exc.detail, status=code)

    name = type(exc).__name__
    msg = str(exc)
    combined = f"{name} {msg}"

    if "ValidationException" in combined:
        return 400, _GENERIC[400]
    if any(
        x in combined
        for x in (
            "ThrottlingException",
            "ServiceQuotaExceeded",
            "TooManyRequests",
            "RequestLimitExceeded",
            "ModelStreamErrorException",
        )
    ):
        return 429, _GENERIC[429]
    if "AccessDenied" in combined or "Unauthorized" in combined:
        return 429, _GENERIC[429]
    return 500, _GENERIC[500]


def raise_upstream_http(exc: BaseException, *, log_label: str = "upstream") -> None:
    """Log full exception server-side, raise sanitized HTTPException."""
    status, detail = status_and_detail_for_upstream(exc)
    logger.error("%s error (client=%s %s): %s", log_label, status, detail, exc)
    raise HTTPException(status_code=status, detail=detail) from None


def scrub_log_error(text: str | None, *, max_len: int = 200) -> str:
    """Scrub provider details before writing/returning request logs."""
    if not text:
        return ""
    raw = str(text)[: max_len * 2]
    if looks_like_upstream_leak(raw):
        return "Upstream error (details redacted)"
    return raw[:max_len]


def public_model_list(models: list[str] | None) -> list[str]:
    """Rewrite allowlists to short public ids only."""
    if not models:
        return []
    try:
        from api.model_alias import to_public
    except Exception:  # noqa: BLE001
        return [m for m in models if m and not looks_like_upstream_leak(m)]

    out: list[str] = []
    seen: set[str] = set()
    for m in models:
        pub = to_public(m) or m
        if looks_like_upstream_leak(pub):
            continue
        if pub and pub not in seen:
            seen.add(pub)
            out.append(pub)
    return out

"""Helpers to record token usage for authenticated API keys."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterable
from typing import Any

from api.auth import ApiKeyContext
from api.db import auth_db
from api.setting import LEGACY_KEY_ID

logger = logging.getLogger(__name__)


def record_usage_from_response(
    key: ApiKeyContext,
    response: Any,
    *,
    model: str = "",
    client_ip: str = "",
    latency_ms: int = 0,
    endpoint: str = "/chat/completions",
) -> None:
    if key.is_legacy or key.key_id == LEGACY_KEY_ID:
        return
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    prompt = getattr(usage, "prompt_tokens", 0) or 0
    completion = getattr(usage, "completion_tokens", 0) or 0
    details = getattr(usage, "prompt_tokens_details", None)
    cache_read = getattr(details, "cached_tokens", 0) or 0
    cache_write = getattr(details, "cache_write_tokens", 0) or 0
    # EmbeddingsUsage has no completion_tokens
    if not hasattr(usage, "completion_tokens"):
        completion = 0
        total = getattr(usage, "total_tokens", None)
        if total is not None:
            prompt = total
    try:
        from api.models.bedrock import get_active_aws_credential

        aws_cred_id, aws_cred_name = get_active_aws_credential()
        auth_db.record_request_usage(
            key.key_id,
            endpoint=endpoint,
            model=model or getattr(response, "model", ""),
            prompt_tokens=prompt,
            completion_tokens=completion,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            client_ip=client_ip,
            latency_ms=latency_ms,
            aws_cred_id=aws_cred_id,
            aws_cred_name=aws_cred_name,
        )
    except Exception:
        logger.exception("Failed to record usage for key_id=%s", key.key_id)


def _parse_stream_usage(chunk: bytes) -> tuple[int, int, int, int] | None:
    """Extract token counts from an SSE usage chunk, if present."""
    if not chunk or b'"usage"' not in chunk:
        return None
    text = chunk.decode("utf-8", errors="ignore").strip()
    # A single SSE event may contain multiple `data:` lines; scan each.
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        usage = data.get("usage")
        if not usage:
            continue
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        details = usage.get("prompt_tokens_details") or {}
        cache_read = int(details.get("cached_tokens") or 0)
        cache_write = int(details.get("cache_write_tokens") or 0)
        if prompt or completion:
            return prompt, completion, cache_read, cache_write
    return None


async def track_chat_stream_usage(
    key: ApiKeyContext,
    stream: AsyncIterable[bytes],
    client_wants_usage: bool = True,
    *,
    model: str = "",
    client_ip: str = "",
    started_at: float | None = None,
) -> AsyncIterable[bytes]:
    """Yield stream chunks and record usage from the final SSE usage event.

    The router forces `stream_options.include_usage` so the upstream always emits a
    final usage chunk. If the original client did not request usage, that chunk is
    suppressed from the forwarded stream after we record it.
    """
    metered = key.is_legacy or key.key_id == LEGACY_KEY_ID
    recorded = False
    async for chunk in stream:
        if not recorded and not metered:
            try:
                usage = _parse_stream_usage(chunk)
            except Exception:
                logger.exception("Failed to parse stream usage for key_id=%s", key.key_id)
                usage = None
            if usage is not None:
                prompt, completion, cache_read, cache_write = usage
                try:
                    import time

                    from api.models.bedrock import get_active_aws_credential

                    latency_ms = int((time.monotonic() - started_at) * 1000) if started_at else 0
                    aws_cred_id, aws_cred_name = get_active_aws_credential()
                    await asyncio.to_thread(
                        auth_db.record_request_usage,
                        key.key_id,
                        endpoint="/chat/completions",
                        model=model,
                        prompt_tokens=prompt,
                        completion_tokens=completion,
                        cache_read_tokens=cache_read,
                        cache_write_tokens=cache_write,
                        client_ip=client_ip,
                        latency_ms=latency_ms,
                        aws_cred_id=aws_cred_id,
                        aws_cred_name=aws_cred_name,
                    )
                    recorded = True
                except Exception:
                    logger.exception("Failed to record usage for key_id=%s", key.key_id)
                # This is the usage-only summary chunk (empty choices). Drop it if the
                # client didn't ask for usage, so we don't change client-facing output.
                if not client_wants_usage:
                    continue
        yield chunk

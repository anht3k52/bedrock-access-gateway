"""OpenAI Responses API compatibility for clients like Sub2API.

Sub2API's OpenAI API-key accounts default to POST {base}/responses.
Our gateway is Chat Completions–native; this adapter converts both ways.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from api.auth import ApiKeyContext, api_key_auth
from api.db import auth_db
from api.model_alias import require_public_model_id, to_bedrock, to_public
from api.models.bedrock import BedrockModel, get_bedrock_model_list
from api.schema import ChatRequest, StreamOptions
from api.setting import DEFAULT_MODEL
from api.usage import record_usage_from_response, track_chat_stream_usage

router = APIRouter(tags=["responses"])


def _client_ip(request: Request) -> str:
    cloudflare_ip = request.headers.get("cf-connecting-ip")
    if cloudflare_ip:
        return cloudflare_ip.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else ""


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                if part.get("type") in ("text", "input_text", "output_text"):
                    parts.append(str(part.get("text") or ""))
                elif "text" in part:
                    parts.append(str(part.get("text") or ""))
        return "".join(parts)
    if isinstance(content, dict):
        return _content_to_text(content.get("text") or content.get("content"))
    return str(content)


def _responses_body_to_chat_request(body: dict[str, Any]) -> ChatRequest:
    model = str(body.get("model") or DEFAULT_MODEL)
    messages: list[dict[str, Any]] = []

    instructions = body.get("instructions")
    if instructions:
        messages.append({"role": "system", "content": _content_to_text(instructions)})

    # Some clients already send Chat Completions shape to /responses
    if isinstance(body.get("messages"), list) and body["messages"]:
        for msg in body["messages"]:
            if isinstance(msg, dict) and msg.get("role"):
                messages.append(
                    {
                        "role": msg["role"],
                        "content": msg.get("content") if msg.get("content") is not None else "",
                    }
                )
    else:
        raw_input = body.get("input")
        if isinstance(raw_input, str):
            messages.append({"role": "user", "content": raw_input})
        elif isinstance(raw_input, list):
            for item in raw_input:
                if isinstance(item, str):
                    messages.append({"role": "user", "content": item})
                elif not isinstance(item, dict):
                    continue
                elif item.get("role"):
                    messages.append(
                        {
                            "role": item["role"],
                            "content": item.get("content")
                            if item.get("content") is not None
                            else _content_to_text(item.get("content")),
                        }
                    )
                elif item.get("type") == "message":
                    messages.append(
                        {
                            "role": item.get("role") or "user",
                            "content": _content_to_text(item.get("content")),
                        }
                    )
                elif item.get("type") in ("input_text", "text", "output_text"):
                    messages.append({"role": "user", "content": _content_to_text(item)})
                else:
                    text = _content_to_text(item)
                    if text:
                        messages.append({"role": "user", "content": text})

    if not messages:
        messages = [{"role": "user", "content": "hi"}]

    # Normalize empty content
    for msg in messages:
        if msg.get("content") is None:
            msg["content"] = ""

    max_tokens = body.get("max_output_tokens") or body.get("max_tokens")
    temperature = body.get("temperature")
    top_p = body.get("top_p")
    stream = bool(body.get("stream"))

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": stream,
    }
    if max_tokens is not None:
        payload["max_tokens"] = int(max_tokens)
    if temperature is not None:
        payload["temperature"] = temperature
    if top_p is not None:
        payload["top_p"] = top_p
    if stream:
        payload["stream_options"] = {"include_usage": True}

    return ChatRequest.model_validate(payload)


def _chat_response_to_responses(chat_response: Any, model: str) -> dict[str, Any]:
    text = ""
    try:
        choice0 = chat_response.choices[0]
        message = choice0.message
        text = message.content or ""
    except Exception:  # noqa: BLE001
        text = ""

    usage = getattr(chat_response, "usage", None)
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
    completion = int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0
    total = int(getattr(usage, "total_tokens", 0) or (prompt + completion)) if usage else 0

    resp_id = f"resp_{secrets.token_hex(12)}"
    msg_id = f"msg_{secrets.token_hex(12)}"
    now = int(time.time())
    return {
        "id": resp_id,
        "object": "response",
        "created_at": now,
        "status": "completed",
        "model": model,
        "output": [
            {
                "type": "message",
                "id": msg_id,
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
        "usage": {
            "input_tokens": prompt,
            "output_tokens": completion,
            "total_tokens": total,
        },
    }


async def _sse_responses_from_chat(
    chat_request: ChatRequest,
    key: ApiKeyContext,
    client_ip: str,
    started_at: float,
    public_model: str,
):
    """Best-effort SSE bridge: emit Responses-like completed event from streamed chat."""
    model = BedrockModel()
    # Collect streamed text then emit a single completed response (simple clients / probes).
    chunks: list[str] = []
    last_usage = None
    async for piece in track_chat_stream_usage(
        key,
        model.chat_stream(chat_request),
        client_wants_usage=True,
        model=public_model,
        client_ip=client_ip,
        started_at=started_at,
    ):
        text_piece = piece.decode("utf-8", errors="ignore") if isinstance(piece, (bytes, bytearray)) else str(piece)
        for line in text_piece.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                continue
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            for choice in obj.get("choices") or []:
                delta = choice.get("delta") or {}
                if delta.get("content"):
                    chunks.append(delta["content"])
            if obj.get("usage"):
                last_usage = obj["usage"]

    text = "".join(chunks)
    prompt = int((last_usage or {}).get("prompt_tokens") or 0)
    completion = int((last_usage or {}).get("completion_tokens") or 0)
    total = int((last_usage or {}).get("total_tokens") or (prompt + completion))
    payload = {
        "id": f"resp_{secrets.token_hex(12)}",
        "object": "response",
        "created_at": int(time.time()),
        "status": "completed",
        "model": public_model,
        "output": [
            {
                "type": "message",
                "id": f"msg_{secrets.token_hex(12)}",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
        "usage": {
            "input_tokens": prompt,
            "output_tokens": completion,
            "total_tokens": total,
        },
    }
    yield f"event: response.completed\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")
    yield b"data: [DONE]\n\n"


@router.post("/responses")
async def create_response(
    request: Request,
    body: Annotated[dict[str, Any], Body(...)],
    key: Annotated[ApiKeyContext, Depends(api_key_auth)],
):
    started_at = time.monotonic()
    client_ip = _client_ip(request)

    try:
        chat_request = _responses_body_to_chat_request(body)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if chat_request.model.lower().startswith("gpt-"):
        chat_request.model = to_public(DEFAULT_MODEL) or "claude-opus-4-6"

    try:
        public_model = require_public_model_id(chat_request.model)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    available = await asyncio.to_thread(lambda: set(get_bedrock_model_list(allow_network=False).keys()))
    bedrock_model = to_bedrock(public_model, available)
    chat_request.model = bedrock_model

    if not key.is_legacy:
        record = auth_db.get_key(key.key_id)
        if record and not (
            record.is_model_allowed(public_model) or record.is_model_allowed(bedrock_model)
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Model '{public_model}' is not allowed for this API key.",
            )

    model = BedrockModel()
    model.validate(chat_request)

    if chat_request.stream:
        if chat_request.stream_options is None:
            chat_request.stream_options = StreamOptions(include_usage=True)
        else:
            chat_request.stream_options.include_usage = True
        return StreamingResponse(
            content=_sse_responses_from_chat(
                chat_request, key, client_ip, started_at, public_model
            ),
            media_type="text/event-stream",
        )

    response = await model.chat(chat_request)
    record_usage_from_response(
        key,
        response,
        model=public_model,
        client_ip=client_ip,
        latency_ms=int((time.monotonic() - started_at) * 1000),
    )
    return _chat_response_to_responses(response, public_model)

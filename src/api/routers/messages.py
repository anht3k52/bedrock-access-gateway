"""Anthropic Messages API compatibility (POST /v1/messages).

Claude Code and the Anthropic SDK speak Messages API; this gateway is Chat
Completions–native. Adapter converts both ways (including SSE streaming).
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

from api.auth import ApiKeyContext, api_key_auth
from api.db import auth_db
from api.model_alias import require_public_model_id, to_bedrock, to_public
from api.models.bedrock import BedrockModel, get_bedrock_model_list
from api.schema import ChatRequest, StreamOptions
from api.setting import DEFAULT_MODEL
from api.usage import record_usage_from_response, track_chat_stream_usage

router = APIRouter(tags=["messages"])

_DEFAULT_MAX_TOKENS = 4096


def _client_ip(request: Request) -> str:
    cloudflare_ip = request.headers.get("cf-connecting-ip")
    if cloudflare_ip:
        return cloudflare_ip.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else ""


def _anthropic_error(status_code: int, message: str, err_type: str = "invalid_request_error") -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"type": "error", "error": {"type": err_type, "message": message}},
    )


def _text_from_content(content: Any) -> str:
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
                elif "text" in part and part.get("type") != "tool_use":
                    parts.append(str(part.get("text") or ""))
        return "".join(parts)
    if isinstance(content, dict):
        return _text_from_content(content.get("text") or content.get("content"))
    return str(content)


def _anthropic_image_to_openai(part: dict[str, Any]) -> dict[str, Any] | None:
    source = part.get("source") or {}
    if not isinstance(source, dict):
        return None
    stype = source.get("type")
    if stype == "base64":
        media = source.get("media_type") or "image/png"
        data = source.get("data") or ""
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{media};base64,{data}"},
        }
    if stype == "url":
        url = source.get("url") or ""
        if url:
            return {"type": "image_url", "image_url": {"url": url}}
    return None


def _convert_user_content(content: Any) -> tuple[Any, list[dict[str, Any]]]:
    """Return (openai_user_content, tool_messages)."""
    tool_msgs: list[dict[str, Any]] = []
    if content is None:
        return "", tool_msgs
    if isinstance(content, str):
        return content, tool_msgs
    if not isinstance(content, list):
        return _text_from_content(content), tool_msgs

    parts: list[dict[str, Any] | str] = []
    for part in content:
        if isinstance(part, str):
            parts.append({"type": "text", "text": part})
            continue
        if not isinstance(part, dict):
            continue
        ptype = part.get("type")
        if ptype == "text":
            parts.append({"type": "text", "text": str(part.get("text") or "")})
        elif ptype == "image":
            img = _anthropic_image_to_openai(part)
            if img:
                parts.append(img)
        elif ptype == "tool_result":
            tool_content = part.get("content")
            if isinstance(tool_content, list):
                tool_content = _text_from_content(tool_content)
            elif tool_content is None:
                tool_content = ""
            else:
                tool_content = str(tool_content)
            tool_msgs.append(
                {
                    "role": "tool",
                    "tool_call_id": str(part.get("tool_use_id") or part.get("id") or ""),
                    "content": tool_content,
                }
            )
        elif ptype == "image_url":
            parts.append(part)

    if not parts and tool_msgs:
        return "", tool_msgs
    if len(parts) == 1 and isinstance(parts[0], dict) and parts[0].get("type") == "text":
        return str(parts[0].get("text") or ""), tool_msgs
    return parts, tool_msgs


def _convert_assistant_content(content: Any) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": "assistant", "content": None}
    if content is None:
        msg["content"] = ""
        return msg
    if isinstance(content, str):
        msg["content"] = content
        return msg
    if not isinstance(content, list):
        msg["content"] = _text_from_content(content)
        return msg

    texts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for i, part in enumerate(content):
        if not isinstance(part, dict):
            continue
        ptype = part.get("type")
        if ptype == "text":
            texts.append(str(part.get("text") or ""))
        elif ptype == "tool_use":
            raw_input = part.get("input")
            if isinstance(raw_input, str):
                args = raw_input
            else:
                args = json.dumps(raw_input if raw_input is not None else {}, ensure_ascii=False)
            tool_calls.append(
                {
                    "index": len(tool_calls),
                    "id": str(part.get("id") or f"toolu_{i}"),
                    "type": "function",
                    "function": {
                        "name": str(part.get("name") or ""),
                        "arguments": args,
                    },
                }
            )
    msg["content"] = "".join(texts) if texts else (None if tool_calls else "")
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg


def _convert_tools(tools: Any) -> list[dict[str, Any]] | None:
    if not isinstance(tools, list) or not tools:
        return None
    out: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        # Already OpenAI-shaped
        if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
            out.append(tool)
            continue
        name = tool.get("name")
        if not name:
            continue
        out.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool.get("description") or "",
                    "parameters": tool.get("input_schema") or tool.get("parameters") or {"type": "object", "properties": {}},
                },
            }
        )
    return out or None


def _convert_tool_choice(tool_choice: Any) -> Any:
    if tool_choice is None:
        return "auto"
    if isinstance(tool_choice, str):
        return tool_choice
    if not isinstance(tool_choice, dict):
        return "auto"
    t = tool_choice.get("type")
    if t == "auto":
        return "auto"
    if t in ("any", "required"):
        return "required"
    if t == "tool" and tool_choice.get("name"):
        return {"type": "function", "function": {"name": tool_choice["name"]}}
    if t == "none":
        return "none"
    return "auto"


def messages_body_to_chat_request(body: dict[str, Any]) -> ChatRequest:
    model = str(body.get("model") or DEFAULT_MODEL)
    messages: list[dict[str, Any]] = []

    system = body.get("system")
    if system:
        messages.append({"role": "system", "content": _text_from_content(system)})

    for raw in body.get("messages") or []:
        if not isinstance(raw, dict):
            continue
        role = raw.get("role")
        content = raw.get("content")
        if role == "user":
            user_content, tool_msgs = _convert_user_content(content)
            messages.extend(tool_msgs)
            if user_content != "" or not tool_msgs:
                messages.append({"role": "user", "content": user_content if user_content != "" else ""})
        elif role == "assistant":
            messages.append(_convert_assistant_content(content))
        elif role == "system":
            messages.append({"role": "system", "content": _text_from_content(content)})
        elif role == "tool":
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": str(raw.get("tool_call_id") or raw.get("tool_use_id") or ""),
                    "content": _text_from_content(content) if not isinstance(content, str) else content,
                }
            )

    if not messages:
        messages = [{"role": "user", "content": "hi"}]

    max_tokens = body.get("max_tokens") or body.get("max_completion_tokens") or _DEFAULT_MAX_TOKENS
    stream = bool(body.get("stream"))
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": stream,
        "max_tokens": int(max_tokens),
    }
    if body.get("temperature") is not None:
        payload["temperature"] = body["temperature"]
    if body.get("top_p") is not None:
        payload["top_p"] = body["top_p"]
    stop = body.get("stop_sequences") or body.get("stop")
    if stop is not None:
        payload["stop"] = stop
    tools = _convert_tools(body.get("tools"))
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = _convert_tool_choice(body.get("tool_choice"))
    if stream:
        payload["stream_options"] = {"include_usage": True}

    # Pass through Anthropic betas / thinking hints when present.
    extra: dict[str, Any] = {}
    if body.get("metadata") is not None:
        extra["metadata"] = body["metadata"]
    betas = body.get("anthropic_beta") or body.get("betas")
    if betas is not None:
        extra["anthropic_beta"] = betas
    if extra:
        payload["extra_body"] = extra

    return ChatRequest.model_validate(payload)


def _map_stop_reason(finish_reason: str | None) -> str:
    mapping = {
        "stop": "end_turn",
        "length": "max_tokens",
        "tool_calls": "tool_use",
        "content_filter": "end_turn",
        "null": "end_turn",
    }
    if not finish_reason:
        return "end_turn"
    return mapping.get(finish_reason, finish_reason)


def chat_response_to_messages(chat_response: Any, model: str) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    stop_reason = "end_turn"
    try:
        choice0 = chat_response.choices[0]
        stop_reason = _map_stop_reason(getattr(choice0, "finish_reason", None))
        message = choice0.message
        text = getattr(message, "content", None)
        if text:
            content.append({"type": "text", "text": text})
        for tc in getattr(message, "tool_calls", None) or []:
            fn = getattr(tc, "function", None)
            name = getattr(fn, "name", None) if fn else None
            args_raw = getattr(fn, "arguments", None) if fn else None
            try:
                parsed = json.loads(args_raw) if isinstance(args_raw, str) and args_raw else (args_raw or {})
            except json.JSONDecodeError:
                parsed = {"raw": args_raw}
            if not isinstance(parsed, dict):
                parsed = {"value": parsed}
            content.append(
                {
                    "type": "tool_use",
                    "id": getattr(tc, "id", None) or f"toolu_{secrets.token_hex(8)}",
                    "name": name or "",
                    "input": parsed,
                }
            )
    except Exception:  # noqa: BLE001
        content = [{"type": "text", "text": ""}]

    if not content:
        content = [{"type": "text", "text": ""}]

    usage = getattr(chat_response, "usage", None)
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
    completion = int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0

    return {
        "id": f"msg_{secrets.token_hex(12)}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": prompt, "output_tokens": completion},
    }


def _sse_event(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")


async def _sse_messages_from_chat(
    chat_request: ChatRequest,
    key: ApiKeyContext,
    client_ip: str,
    started_at: float,
    public_model: str,
):
    """Convert OpenAI chat SSE chunks into Anthropic Messages SSE events."""
    model = BedrockModel()
    msg_id = f"msg_{secrets.token_hex(12)}"
    started = False
    text_index: int | None = None
    tool_indexes: dict[int, int] = {}  # openai tool index → content block index
    next_block = 0
    open_block: int | None = None
    stop_reason = "end_turn"
    input_tokens = 0
    output_tokens = 0

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
            if not data or data == "[DONE]":
                continue
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue

            # OpenAI-style stream error (already sanitized upstream)
            if obj.get("error"):
                err = obj["error"]
                msg = err.get("message") if isinstance(err, dict) else str(err)
                from api.safe_errors import client_safe_detail

                yield _sse_event(
                    "error",
                    {
                        "type": "error",
                        "error": {
                            "type": "api_error",
                            "message": client_safe_detail(msg, status=500),
                        },
                    },
                )
                return

            if obj.get("usage"):
                input_tokens = int(obj["usage"].get("prompt_tokens") or input_tokens or 0)
                output_tokens = int(obj["usage"].get("completion_tokens") or output_tokens or 0)

            for choice in obj.get("choices") or []:
                finish = choice.get("finish_reason")
                if finish:
                    stop_reason = _map_stop_reason(finish)
                delta = choice.get("delta") or {}

                if not started:
                    started = True
                    yield _sse_event(
                        "message_start",
                        {
                            "type": "message_start",
                            "message": {
                                "id": msg_id,
                                "type": "message",
                                "role": "assistant",
                                "model": public_model,
                                "content": [],
                                "stop_reason": None,
                                "stop_sequence": None,
                                "usage": {"input_tokens": input_tokens or 0, "output_tokens": 0},
                            },
                        },
                    )

                content = delta.get("content")
                if content:
                    if text_index is None:
                        if open_block is not None:
                            yield _sse_event(
                                "content_block_stop",
                                {"type": "content_block_stop", "index": open_block},
                            )
                            open_block = None
                        text_index = next_block
                        next_block += 1
                        open_block = text_index
                        yield _sse_event(
                            "content_block_start",
                            {
                                "type": "content_block_start",
                                "index": text_index,
                                "content_block": {"type": "text", "text": ""},
                            },
                        )
                    yield _sse_event(
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": text_index,
                            "delta": {"type": "text_delta", "text": content},
                        },
                    )

                for tc in delta.get("tool_calls") or []:
                    if not isinstance(tc, dict):
                        continue
                    oi = int(tc.get("index") or 0)
                    fn = tc.get("function") or {}
                    if oi not in tool_indexes:
                        if open_block is not None:
                            yield _sse_event(
                                "content_block_stop",
                                {"type": "content_block_stop", "index": open_block},
                            )
                            open_block = None
                        bi = next_block
                        next_block += 1
                        tool_indexes[oi] = bi
                        open_block = bi
                        yield _sse_event(
                            "content_block_start",
                            {
                                "type": "content_block_start",
                                "index": bi,
                                "content_block": {
                                    "type": "tool_use",
                                    "id": tc.get("id") or f"toolu_{secrets.token_hex(8)}",
                                    "name": fn.get("name") or "",
                                    "input": {},
                                },
                            },
                        )
                    args = fn.get("arguments")
                    if args:
                        yield _sse_event(
                            "content_block_delta",
                            {
                                "type": "content_block_delta",
                                "index": tool_indexes[oi],
                                "delta": {"type": "input_json_delta", "partial_json": args},
                            },
                        )

    if not started:
        # Empty / failed stream — still emit a minimal valid sequence.
        yield _sse_event(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": msg_id,
                    "type": "message",
                    "role": "assistant",
                    "model": public_model,
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                },
            },
        )
        text_index = 0
        open_block = 0
        yield _sse_event(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        )

    if open_block is not None:
        yield _sse_event(
            "content_block_stop",
            {"type": "content_block_stop", "index": open_block},
        )

    yield _sse_event(
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason, "stop_sequence": None},
            "usage": {"output_tokens": output_tokens},
        },
    )
    yield _sse_event("message_stop", {"type": "message_stop"})


@router.post("/messages")
async def create_message(
    request: Request,
    body: Annotated[dict[str, Any], Body(...)],
    key: Annotated[ApiKeyContext, Depends(api_key_auth)],
):
    started_at = time.monotonic()
    client_ip = _client_ip(request)

    try:
        chat_request = messages_body_to_chat_request(body)
    except Exception as exc:  # noqa: BLE001
        from api.safe_errors import client_safe_detail

        return _anthropic_error(400, client_safe_detail(str(exc), status=400))

    if chat_request.model.lower().startswith("gpt-"):
        chat_request.model = to_public(DEFAULT_MODEL) or "claude-opus-4-6"

    try:
        public_model = require_public_model_id(chat_request.model)
    except ValueError as exc:
        return _anthropic_error(400, str(exc))

    available = await asyncio.to_thread(lambda: set(get_bedrock_model_list(allow_network=False).keys()))
    bedrock_model = to_bedrock(public_model, available)
    chat_request.model = bedrock_model

    if not key.is_legacy:
        record = await asyncio.to_thread(auth_db.get_key, key.key_id)
        if record and not (
            record.is_model_allowed(public_model) or record.is_model_allowed(bedrock_model)
        ):
            return _anthropic_error(
                403,
                f"Model '{public_model}' is not allowed for this API key.",
                err_type="permission_error",
            )

    model = BedrockModel()
    try:
        await asyncio.to_thread(model.validate, chat_request)
    except HTTPException as exc:
        from api.safe_errors import client_safe_detail

        return _anthropic_error(exc.status_code, client_safe_detail(exc.detail, status=exc.status_code))
    except Exception as exc:  # noqa: BLE001
        from api.safe_errors import status_and_detail_for_upstream

        code, msg = status_and_detail_for_upstream(exc)
        return _anthropic_error(code, msg)

    if chat_request.stream:
        if chat_request.stream_options is None:
            chat_request.stream_options = StreamOptions(include_usage=True)
        else:
            chat_request.stream_options.include_usage = True
        return StreamingResponse(
            content=_sse_messages_from_chat(
                chat_request, key, client_ip, started_at, public_model
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "x-api-type": "anthropic-messages",
            },
        )

    try:
        response = await model.chat(chat_request)
    except HTTPException as exc:
        from api.safe_errors import client_safe_detail

        code = exc.status_code
        err_type = "rate_limit_error" if code == 429 else "api_error"
        return _anthropic_error(code, client_safe_detail(exc.detail, status=code), err_type=err_type)
    except Exception as exc:  # noqa: BLE001
        from api.safe_errors import status_and_detail_for_upstream

        code, msg = status_and_detail_for_upstream(exc)
        err_type = "rate_limit_error" if code == 429 else "api_error"
        return _anthropic_error(code, msg, err_type=err_type)

    await asyncio.to_thread(
        record_usage_from_response,
        key,
        response,
        model=public_model,
        client_ip=client_ip,
        latency_ms=int((time.monotonic() - started_at) * 1000),
    )
    return chat_response_to_messages(response, public_model)


@router.get("/messages")
async def messages_probe():
    """Simple discovery probe (some clients GET the path)."""
    return {
        "type": "ok",
        "api": "anthropic-messages",
        "path": "/v1/messages",
        "note": "Use POST with x-api-key or Authorization: Bearer",
    }

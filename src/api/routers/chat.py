import asyncio
import time
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from api.auth import ApiKeyContext, api_key_auth
from api.db import auth_db
from api.model_alias import require_public_model_id, to_bedrock, to_public
from api.models.bedrock import BedrockModel, get_bedrock_model_list
from api.schema import ChatRequest, ChatResponse, ChatStreamResponse, Error, StreamOptions
from api.setting import DEFAULT_MODEL
from api.usage import record_usage_from_response, track_chat_stream_usage

router = APIRouter(
    prefix="/chat",
)


def _client_ip(request: Request) -> str:
    cloudflare_ip = request.headers.get("cf-connecting-ip")
    if cloudflare_ip:
        return cloudflare_ip.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else ""


@router.post(
    "/completions", response_model=ChatResponse | ChatStreamResponse | Error, response_model_exclude_unset=True
)
async def chat_completions(
    request: Request,
    chat_request: Annotated[
        ChatRequest,
        Body(
            examples=[
                {
                    "model": "claude-opus-4-6",
                    "messages": [
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": "Hello!"},
                    ],
                }
            ],
        ),
    ],
    key: Annotated[ApiKeyContext, Depends(api_key_auth)],
):
    started_at = time.monotonic()
    client_ip = _client_ip(request)
    if chat_request.model.lower().startswith("gpt-"):
        chat_request.model = to_public(DEFAULT_MODEL) or "claude-opus-4-6"

    # Clients may only send short public ids; server maps to upstream internally.
    try:
        public_model = require_public_model_id(chat_request.model)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    available = await asyncio.to_thread(lambda: set(get_bedrock_model_list(allow_network=False).keys()))
    bedrock_model = to_bedrock(public_model, available)
    chat_request.model = bedrock_model

    if not key.is_legacy:
        record = await asyncio.to_thread(auth_db.get_key, key.key_id)
        if record and not (
            record.is_model_allowed(public_model) or record.is_model_allowed(bedrock_model)
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Model '{public_model}' is not allowed for this API key.",
            )

    # Exception will be raised if model not supported.
    model = BedrockModel()
    # validate is cache-only / non-blocking, but keep it off the event loop anyway.
    await asyncio.to_thread(model.validate, chat_request)
    if chat_request.stream:
        # Force Bedrock to emit a final usage chunk so we can meter tokens,
        # even if the client (e.g. Claude Code via ccr) did not ask for usage.
        client_wants_usage = bool(
            chat_request.stream_options and chat_request.stream_options.include_usage
        )
        if chat_request.stream_options is None:
            chat_request.stream_options = StreamOptions(include_usage=True)
        else:
            chat_request.stream_options.include_usage = True

        async def _public_model_stream():
            needle = f'"model":"{bedrock_model}"'.encode()
            repl = f'"model":"{public_model}"'.encode()
            async for chunk in model.chat_stream(chat_request):
                if needle in chunk:
                    chunk = chunk.replace(needle, repl)
                yield chunk

        return StreamingResponse(
            content=track_chat_stream_usage(
                key,
                _public_model_stream(),
                client_wants_usage=client_wants_usage,
                model=public_model,
                client_ip=client_ip,
                started_at=started_at,
            ),
            media_type="text/event-stream",
        )
    response = await model.chat(chat_request)
    if hasattr(response, "model"):
        response.model = public_model
    await asyncio.to_thread(
        record_usage_from_response,
        key,
        response,
        model=public_model,
        client_ip=client_ip,
        latency_ms=int((time.monotonic() - started_at) * 1000),
    )
    return response

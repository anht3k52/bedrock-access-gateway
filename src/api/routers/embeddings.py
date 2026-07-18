import time
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Request

from api.auth import ApiKeyContext, api_key_auth
from api.models.bedrock import get_embeddings_model
from api.schema import EmbeddingsRequest, EmbeddingsResponse
from api.setting import DEFAULT_EMBEDDING_MODEL
from api.usage import record_usage_from_response

router = APIRouter(
    prefix="/embeddings",
)


@router.post("", response_model=EmbeddingsResponse)
async def embeddings(
    request: Request,
    embeddings_request: Annotated[
        EmbeddingsRequest,
        Body(
            examples=[
                {
                    "model": "cohere.embed-multilingual-v3",
                    "input": ["Your text string goes here"],
                }
            ],
        ),
    ],
    key: Annotated[ApiKeyContext, Depends(api_key_auth)],
):
    started_at = time.monotonic()
    if embeddings_request.model.lower().startswith("text-embedding-"):
        embeddings_request.model = DEFAULT_EMBEDDING_MODEL
    # Exception will be raised if model not supported.
    model = get_embeddings_model(embeddings_request.model)
    response = model.embed(embeddings_request)
    forwarded = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "")
    client_ip = forwarded.split(",", 1)[0].strip() if forwarded else (
        request.client.host if request.client else ""
    )
    record_usage_from_response(
        key,
        response,
        model=embeddings_request.model,
        client_ip=client_ip,
        latency_ms=int((time.monotonic() - started_at) * 1000),
        endpoint="/embeddings",
    )
    return response

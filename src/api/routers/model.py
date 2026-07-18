import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from api.auth import ApiKeyContext, api_key_auth
from api.db import auth_db
from api.model_alias import (
    is_internal_model_id,
    is_public_model,
    list_public_ids,
    require_public_model_id,
    to_public,
)
from api.models.bedrock import BedrockModel
from api.schema import Model, Models

router = APIRouter(prefix="/models")

chat_model = BedrockModel()


def _public_catalog() -> list[str]:
    return list_public_ids(chat_model.list_models())


def _filter_for_key(ids: list[str], key: ApiKeyContext) -> list[str]:
    if key.is_legacy:
        return ids
    record = auth_db.get_key(key.key_id)
    if not record or not record.allowed_models_list:
        return ids
    return [mid for mid in ids if record.is_model_allowed(mid)]


async def validate_model_id(model_id: str):
    if is_internal_model_id(model_id) or (model_id or "").lower().startswith("mrdev/"):
        try:
            require_public_model_id(model_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    public_ids = await asyncio.to_thread(_public_catalog)
    short = to_public(model_id)
    if model_id in public_ids or short in public_ids:
        return
    raise HTTPException(status_code=404, detail="Unsupported Model Id")


@router.get("", response_model=Models)
async def list_models(key: Annotated[ApiKeyContext, Depends(api_key_auth)]):
    ids = await asyncio.to_thread(_public_catalog)
    ids = await asyncio.to_thread(_filter_for_key, ids, key)
    return Models(data=[Model(id=model_id) for model_id in ids])


@router.get(
    "/{model_id:path}",
    response_model=Model,
)
async def get_model(
    model_id: Annotated[
        str,
        Path(description="Model ID", example="claude-opus-4-8"),
    ],
    key: Annotated[ApiKeyContext, Depends(api_key_auth)],
):
    await validate_model_id(model_id)
    _ = key  # auth required
    return Model(id=model_id if is_public_model(model_id) else to_public(model_id))

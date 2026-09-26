from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from authz.auth import require_api_key
from schemas.openai_compat import ImageCreate
from services import completions

router = APIRouter(tags=["images"])


@router.post("/v1/images/generations", dependencies=[Depends(require_api_key)])
async def images_generations(body: ImageCreate, request: Request):
    return await completions.enqueue_image(request.scope["env"], body)

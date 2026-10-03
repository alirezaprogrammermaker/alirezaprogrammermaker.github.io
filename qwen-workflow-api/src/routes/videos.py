from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from authz.auth import require_api_key
from schemas.openai_compat import VideoCreate
from services import completions

router = APIRouter(tags=["videos"])


@router.post("/v1/videos/generations", dependencies=[Depends(require_api_key)])
async def videos_generations(body: VideoCreate, request: Request):
    return await completions.enqueue_video(request.scope["env"], body)

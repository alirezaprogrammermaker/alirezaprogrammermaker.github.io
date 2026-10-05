from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from authz.auth import require_api_key
from schemas.openai_compat import ChatCompletionCreate
from services import completions

router = APIRouter(tags=["chat"])


@router.post("/v1/chat/completions", dependencies=[Depends(require_api_key)])
async def chat_completions(body: ChatCompletionCreate, request: Request):
    """OpenAI-compatible text endpoint (async job under the hood).

    Extensions in response: status, chat_id, account_id, qwen_chat_id.
    Poll GET /v1/jobs/{id} until status=succeeded|failed.
    """
    job = await completions.enqueue_text(request.scope["env"], body)
    return job

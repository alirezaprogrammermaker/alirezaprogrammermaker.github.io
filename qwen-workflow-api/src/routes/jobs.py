from __future__ import annotations


from fastapi import APIRouter, Depends, HTTPException, Request

from db.repos import jobs as jobs_repo
from authz.auth import require_api_key
from services.completions import job_to_openai_shape

router = APIRouter(tags=["jobs"])


@router.get("/v1/jobs/{job_id}", dependencies=[Depends(require_api_key)])
async def get_job(job_id: str, request: Request):
    row = await jobs_repo.get(request.scope["env"].DB, job_id)
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    return job_to_openai_shape(row)


@router.get("/v1/chat/completions/{job_id}", dependencies=[Depends(require_api_key)])
async def get_completion(job_id: str, request: Request):
    row = await jobs_repo.get(request.scope["env"].DB, job_id)
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    return job_to_openai_shape(row)


@router.get("/v1/chats/{chat_id}", dependencies=[Depends(require_api_key)])
async def get_chat(chat_id: str, request: Request):
    from db.repos import chats as chats_repo
    from db.repos import messages as messages_repo

    chat = await chats_repo.get(request.scope["env"].DB, chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="chat not found")
    msgs = await messages_repo.list_for_chat(request.scope["env"].DB, chat_id, limit=100)
    return {"chat": chat, "messages": msgs}

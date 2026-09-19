from __future__ import annotations

import json

from fastapi import HTTPException

from constants import STATUS_FAILED, STATUS_SUCCEEDED
from db.repos import accounts as accounts_repo
from db.repos import chats as chats_repo
from db.repos import jobs as jobs_repo
from db.repos import messages as messages_repo
from security.crypto import open_sealed


async def claim_next(env, worker_id: str) -> dict | None:
    db = env.DB
    peeked = await jobs_repo.peek_queued(db)
    if not peeked:
        return None  # 1 read, 0 writes when idle

    claimed = await jobs_repo.claim(db, peeked["id"], worker_id)
    if not claimed:
        return None

    account = await accounts_repo.get(db, claimed["account_id"])
    if not account:
        await jobs_repo.complete(db, claimed["id"], status=STATUS_FAILED, error="account missing")
        raise HTTPException(status_code=409, detail="account missing for job")

    secret = getattr(env, "ACCOUNT_SECRET", None)
    password = open_sealed(account["password_enc"], secret)

    request = {}
    try:
        request = json.loads(claimed.get("request_json") or "{}")
    except Exception:
        request = {}

    return {
        "job": {
            "id": claimed["id"],
            "chat_id": claimed.get("chat_id"),
            "account_id": claimed["account_id"],
            "qwen_chat_id": claimed.get("qwen_chat_id"),
            "kind": claimed["kind"],
            "model": claimed.get("model"),
            "request": request,
            "status": claimed["status"],
        },
        "account": {
            "id": account["id"],
            "name": account["name"],
            "email": account["email"],
            "password": password,
        },
    }


async def complete_job(env, job_id: str, body) -> dict:
    db = env.DB
    job = await jobs_repo.get(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")

    status = body.status
    if status not in (STATUS_SUCCEEDED, STATUS_FAILED):
        raise HTTPException(status_code=400, detail="status must be succeeded|failed")

    await jobs_repo.complete(
        db,
        job_id,
        status=status,
        result=body.result,
        error=body.error,
        qwen_chat_id=body.qwen_chat_id,
    )

    if body.qwen_chat_id and job.get("chat_id"):
        await chats_repo.set_qwen_chat_id(db, job["chat_id"], body.qwen_chat_id)

    if status == STATUS_SUCCEEDED and job.get("chat_id"):
        content = body.assistant_content
        if not content and isinstance(body.result, dict):
            content = body.result.get("content") or body.result.get("text")
        if content:
            await messages_repo.add(
                db,
                chat_id=job["chat_id"],
                role="assistant",
                content=content,
                job_id=job_id,
            )

    fresh = await jobs_repo.get(db, job_id)
    return fresh

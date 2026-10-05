from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException

from constants import KIND_IMAGE, KIND_TEXT, KIND_VIDEO, MODEL_KIND, STATUS_SUCCEEDED
from db.repos import accounts as accounts_repo
from db.repos import chats as chats_repo
from db.repos import jobs as jobs_repo
from db.repos import messages as messages_repo
from services.accounts import resolve_account


def kind_from_model(model: str) -> str:
    kind = MODEL_KIND.get((model or "").lower())
    if not kind:
        raise HTTPException(status_code=400, detail=f"Unsupported model '{model}'")
    return kind


def _user_text_from_messages(messages: list[dict]) -> str:
    parts = [m["content"] for m in messages if m.get("role") == "user" and m.get("content")]
    if not parts:
        raise HTTPException(status_code=400, detail="At least one user message is required")
    return parts[-1]


async def enqueue_text(env, body) -> dict[str, Any]:
    if body.stream:
        raise HTTPException(status_code=400, detail="stream=true is not supported yet")
    kind = kind_from_model(body.model)
    if kind != KIND_TEXT:
        raise HTTPException(status_code=400, detail="Use /v1/images/generations or /v1/videos/generations for non-text")
    return await _enqueue(
        env,
        kind=KIND_TEXT,
        model=body.model,
        prompt=_user_text_from_messages([m.model_dump() for m in body.messages]),
        messages=[m.model_dump() for m in body.messages],
        chat_id=body.chat_id,
        account_id=body.account_id,
        extra={"think": body.think or "auto"},
    )


async def enqueue_image(env, body) -> dict[str, Any]:
    return await _enqueue(
        env,
        kind=KIND_IMAGE,
        model=body.model,
        prompt=body.prompt,
        messages=[{"role": "user", "content": body.prompt}],
        chat_id=body.chat_id,
        account_id=body.account_id,
        extra={"n": body.n, "size": body.size},
    )


async def enqueue_video(env, body) -> dict[str, Any]:
    return await _enqueue(
        env,
        kind=KIND_VIDEO,
        model=body.model,
        prompt=body.prompt,
        messages=[{"role": "user", "content": body.prompt}],
        chat_id=body.chat_id,
        account_id=body.account_id,
        extra={},
    )


async def _enqueue(
    env,
    *,
    kind: str,
    model: str,
    prompt: str,
    messages: list[dict],
    chat_id: str | None,
    account_id: str | None,
    extra: dict,
) -> dict[str, Any]:
    db = env.DB
    qwen_chat_id = None
    chat = None

    if chat_id:
        # ONE read resolves account + upstream chat binding
        chat = await chats_repo.get(db, chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="chat_id not found")
        if account_id and account_id != chat["account_id"]:
            raise HTTPException(
                status_code=400,
                detail="account_id does not match the account bound to this chat_id",
            )
        account = await accounts_repo.get(db, chat["account_id"])
        if not account or account.get("status") != "active":
            raise HTTPException(status_code=400, detail="Bound account is not available")
        qwen_chat_id = chat.get("qwen_chat_id")
    else:
        account = await resolve_account(env, account_id=account_id)
        chat = await chats_repo.create(
            db,
            account_id=account["id"],
            modality=kind,
            title=(prompt[:80] if prompt else None),
        )
        chat_id = chat["id"]

    request = {
        "kind": kind,
        "model": model,
        "prompt": prompt,
        "messages": messages,
        "think": extra.get("think", "auto"),
        "n": extra.get("n"),
        "size": extra.get("size"),
        "mode": {"text": "chat", "image": "image", "video": "video"}[kind],
    }

    job = await jobs_repo.create(
        db,
        kind=kind,
        account_id=account["id"],
        request=request,
        chat_id=chat_id,
        qwen_chat_id=qwen_chat_id,
        model=model,
    )
    await messages_repo.add(db, chat_id=chat_id, role="user", content=prompt, job_id=job["id"])
    await accounts_repo.touch(db, account["id"])
    await chats_repo.touch(db, chat_id)

    return job_to_openai_shape(job, result=None)


def job_to_openai_shape(job: dict, result: dict | None = None) -> dict[str, Any]:
    status = job.get("status")
    result_json = result
    if result_json is None and job.get("result_json"):
        try:
            result_json = json.loads(job["result_json"])
        except Exception:
            result_json = None

    choices = []
    if status == STATUS_SUCCEEDED and result_json:
        content = result_json.get("content") or result_json.get("text") or ""
        choices = [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ]
        # image/video passthrough
        if result_json.get("images"):
            choices[0]["message"]["images"] = result_json["images"]
        if result_json.get("videos"):
            choices[0]["message"]["videos"] = result_json["videos"]

    return {
        "id": job["id"],
        "object": "chat.completion" if job.get("kind") == KIND_TEXT else f"qwen.{job.get('kind')}.job",
        "created": job.get("created_at"),
        "model": job.get("model"),
        "status": status,  # extension (queued|running|succeeded|failed)
        "kind": job.get("kind"),
        "chat_id": job.get("chat_id"),          # extension
        "account_id": job.get("account_id"),    # extension — bound account
        "qwen_chat_id": job.get("qwen_chat_id"),
        "choices": choices,
        "error": job.get("error"),
        "result": result_json,
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }

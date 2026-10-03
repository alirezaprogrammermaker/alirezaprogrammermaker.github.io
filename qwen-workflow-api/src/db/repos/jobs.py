from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional

from constants import LEASE_SECONDS, STATUS_QUEUED, STATUS_RUNNING
from db import d1


async def create(
    db,
    *,
    kind: str,
    account_id: str,
    request: dict[str, Any],
    chat_id: str | None = None,
    qwen_chat_id: str | None = None,
    model: str | None = None,
) -> dict:
    now = int(time.time())
    jid = str(uuid.uuid4())
    await d1.run(
        db,
        """
        INSERT INTO jobs (
          id, chat_id, account_id, qwen_chat_id, kind, status, model,
          request_json, result_json, error, lease_owner, lease_until,
          created_at, updated_at, finished_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, ?, ?, NULL)
        """,
        jid, chat_id, account_id, qwen_chat_id, kind, STATUS_QUEUED, model,
        json.dumps(request, ensure_ascii=False), now, now,
    )
    return {
        "id": jid,
        "chat_id": chat_id,
        "account_id": account_id,
        "qwen_chat_id": qwen_chat_id,
        "kind": kind,
        "status": STATUS_QUEUED,
        "model": model,
        "created_at": now,
        "updated_at": now,
    }


async def get(db, job_id: str) -> Optional[dict]:
    return await d1.one(db, "SELECT * FROM jobs WHERE id = ?", job_id)


async def peek_queued(db) -> Optional[dict]:
    """Read-only peek — no write when queue empty (saves D1 write quota)."""
    return await d1.one(
        db,
        """
        SELECT id, chat_id, account_id, qwen_chat_id, kind, status, model,
               request_json, created_at
        FROM jobs
        WHERE status = ?
           OR (status = ? AND lease_until IS NOT NULL AND lease_until < ?)
        ORDER BY created_at ASC
        LIMIT 1
        """,
        STATUS_QUEUED,
        STATUS_RUNNING,
        int(time.time()),
    )


async def claim(db, job_id: str, worker_id: str) -> Optional[dict]:
    now = int(time.time())
    lease_until = now + LEASE_SECONDS
    await d1.run(
        db,
        """
        UPDATE jobs
        SET status = ?, lease_owner = ?, lease_until = ?, updated_at = ?
        WHERE id = ?
          AND (
            status = ?
            OR (status = ? AND lease_until IS NOT NULL AND lease_until < ?)
          )
        """,
        STATUS_RUNNING, worker_id, lease_until, now, job_id,
        STATUS_QUEUED, STATUS_RUNNING, now,
    )
    row = await d1.one(db, "SELECT * FROM jobs WHERE id = ? AND lease_owner = ?", job_id, worker_id)
    return row


async def complete(
    db,
    job_id: str,
    *,
    status: str,
    result: dict | None = None,
    error: str | None = None,
    qwen_chat_id: str | None = None,
) -> None:
    now = int(time.time())
    await d1.run(
        db,
        """
        UPDATE jobs
        SET status = ?,
            result_json = ?,
            error = ?,
            qwen_chat_id = COALESCE(?, qwen_chat_id),
            lease_owner = NULL,
            lease_until = NULL,
            updated_at = ?,
            finished_at = ?
        WHERE id = ?
        """,
        status,
        json.dumps(result, ensure_ascii=False) if result is not None else None,
        error,
        qwen_chat_id,
        now,
        now,
        job_id,
    )

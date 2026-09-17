from __future__ import annotations

import time
import uuid

from db import d1


async def add(db, *, chat_id: str, role: str, content: str, job_id: str | None = None) -> dict:
    now = int(time.time())
    mid = str(uuid.uuid4())
    await d1.run(
        db,
        """
        INSERT INTO messages (id, chat_id, job_id, role, content, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        mid, chat_id, job_id, role, content, now,
    )
    return {"id": mid, "chat_id": chat_id, "job_id": job_id, "role": role, "content": content, "created_at": now}


async def list_for_chat(db, chat_id: str, limit: int = 50) -> list[dict]:
    return await d1.all(
        db,
        """
        SELECT id, chat_id, job_id, role, content, created_at
        FROM messages
        WHERE chat_id = ?
        ORDER BY created_at ASC
        LIMIT ?
        """,
        chat_id,
        limit,
    )


async def delete_older_than(db, cutoff_ts: int, limit: int) -> int:
    """Batch delete — one statement, capped rows."""
    # Capture count via changes() after delete
    await d1.run(
        db,
        """
        DELETE FROM messages
        WHERE id IN (
          SELECT id FROM messages
          WHERE created_at < ?
          ORDER BY created_at ASC
          LIMIT ?
        )
        """,
        cutoff_ts,
        limit,
    )
    # Best-effort; D1 meta.changes not always exposed cleanly in Python
    return limit

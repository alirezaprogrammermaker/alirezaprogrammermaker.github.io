from __future__ import annotations

import time

from constants import CLEANUP_BATCH, CLEANUP_DAYS
from db import d1


async def purge_old_rows(env) -> dict:
    """Daily cron: delete rows older than CLEANUP_DAYS in capped batches.

    Order: messages → jobs → chats (avoid orphans lingering forever).
    Uses indexed created_at / updated_at and LIMIT to control D1 writes.
    """
    db = env.DB
    cutoff = int(time.time()) - CLEANUP_DAYS * 24 * 3600
    limit = CLEANUP_BATCH

    await d1.run(
        db,
        """
        DELETE FROM messages WHERE id IN (
          SELECT id FROM messages WHERE created_at < ? ORDER BY created_at ASC LIMIT ?
        )
        """,
        cutoff, limit,
    )
    await d1.run(
        db,
        """
        DELETE FROM jobs WHERE id IN (
          SELECT id FROM jobs
          WHERE created_at < ? AND status IN ('succeeded','failed')
          ORDER BY created_at ASC LIMIT ?
        )
        """,
        cutoff, limit,
    )
    await d1.run(
        db,
        """
        DELETE FROM chats WHERE id IN (
          SELECT c.id FROM chats c
          WHERE c.updated_at < ?
            AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.chat_id = c.id)
            AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.chat_id = c.id)
          ORDER BY c.updated_at ASC LIMIT ?
        )
        """,
        cutoff, limit,
    )
    return {"cutoff": cutoff, "batch": limit}

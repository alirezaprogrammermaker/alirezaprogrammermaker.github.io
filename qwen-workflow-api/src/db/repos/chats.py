from __future__ import annotations

import time
import uuid
from typing import Optional

from db import d1


async def create(db, *, account_id: str, modality: str, title: str | None = None,
                 qwen_chat_id: str | None = None, chat_id: str | None = None) -> dict:
    now = int(time.time())
    cid = chat_id or str(uuid.uuid4())
    await d1.run(
        db,
        """
        INSERT INTO chats (id, account_id, qwen_chat_id, title, modality, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        cid, account_id, qwen_chat_id, title, modality, now, now,
    )
    return {
        "id": cid,
        "account_id": account_id,
        "qwen_chat_id": qwen_chat_id,
        "title": title,
        "modality": modality,
        "created_at": now,
        "updated_at": now,
    }


async def get(db, chat_id: str) -> Optional[dict]:
    return await d1.one(
        db,
        """
        SELECT id, account_id, qwen_chat_id, title, modality, created_at, updated_at
        FROM chats WHERE id = ?
        """,
        chat_id,
    )


async def set_qwen_chat_id(db, chat_id: str, qwen_chat_id: str) -> None:
    now = int(time.time())
    await d1.run(
        db,
        "UPDATE chats SET qwen_chat_id = ?, updated_at = ? WHERE id = ?",
        qwen_chat_id, now, chat_id,
    )


async def touch(db, chat_id: str) -> None:
    now = int(time.time())
    await d1.run(db, "UPDATE chats SET updated_at = ? WHERE id = ?", now, chat_id)

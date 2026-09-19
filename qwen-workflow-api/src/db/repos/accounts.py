from __future__ import annotations

import time
import uuid
from typing import Any, Optional

from constants import ACCOUNT_ACTIVE
from db import d1


async def create(db, *, name: str, email: str, password_enc: str) -> dict:
    now = int(time.time())
    aid = str(uuid.uuid4())
    await d1.run(
        db,
        """
        INSERT INTO accounts (id, name, email, password_enc, status, last_used_at, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, NULL, ?, ?)
        """,
        aid, name, email, password_enc, ACCOUNT_ACTIVE, now, now,
    )
    return {
        "id": aid,
        "name": name,
        "email": email,
        "status": ACCOUNT_ACTIVE,
        "created_at": now,
        "updated_at": now,
        "last_used_at": None,
    }


async def list_public(db) -> list[dict]:
    return await d1.all(
        db,
        """
        SELECT id, name, email, status, last_used_at, created_at, updated_at
        FROM accounts
        ORDER BY created_at DESC
        """,
    )


async def get(db, account_id: str) -> Optional[dict]:
    return await d1.one(
        db,
        """
        SELECT id, name, email, password_enc, status, last_used_at, created_at, updated_at
        FROM accounts WHERE id = ?
        """,
        account_id,
    )


async def get_by_name(db, name: str) -> Optional[dict]:
    return await d1.one(db, "SELECT id, name, email, status FROM accounts WHERE name = ?", name)


async def pick_least_recently_used(db) -> Optional[dict]:
    """Single read — prefer accounts that haven't been used recently."""
    return await d1.one(
        db,
        """
        SELECT id, name, email, password_enc, status, last_used_at
        FROM accounts
        WHERE status = ?
        ORDER BY last_used_at IS NOT NULL, last_used_at ASC, created_at ASC
        LIMIT 1
        """,
        ACCOUNT_ACTIVE,
    )


async def touch(db, account_id: str) -> None:
    now = int(time.time())
    await d1.run(
        db,
        "UPDATE accounts SET last_used_at = ?, updated_at = ? WHERE id = ?",
        now, now, account_id,
    )


async def set_status(db, account_id: str, status: str) -> None:
    now = int(time.time())
    await d1.run(
        db,
        "UPDATE accounts SET status = ?, updated_at = ? WHERE id = ?",
        status, now, account_id,
    )


async def delete(db, account_id: str) -> bool:
    res = await d1.run(db, "DELETE FROM accounts WHERE id = ?", account_id)
    # meta may vary; treat as best-effort
    return True

from __future__ import annotations

import re

from fastapi import HTTPException

from db.repos import accounts as accounts_repo
from security.crypto import seal


def _default_name(email: str) -> str:
    prefix = email.split("@", 1)[0]
    name = re.sub(r"[^a-zA-Z0-9_-]+", "_", prefix).strip("_").lower() or "account"
    return name[:64]


async def add_account(env, *, email: str, password: str, name: str | None):
    secret = getattr(env, "ACCOUNT_SECRET", None)
    if not secret:
        raise HTTPException(status_code=500, detail="ACCOUNT_SECRET not configured")
    db = env.DB
    account_name = name or _default_name(email)
    existing = await accounts_repo.get_by_name(db, account_name)
    if existing:
        raise HTTPException(status_code=409, detail=f"Account name '{account_name}' already exists")
    password_enc = seal(password, secret)
    row = await accounts_repo.create(
        db, name=account_name, email=email, password_enc=password_enc
    )
    return row


async def list_accounts(env):
    return await accounts_repo.list_public(env.DB)


async def resolve_account(env, *, account_id: str | None = None) -> dict:
    db = env.DB
    if account_id:
        row = await accounts_repo.get(db, account_id)
        if not row:
            raise HTTPException(status_code=404, detail="account_id not found")
        if row.get("status") != "active":
            raise HTTPException(status_code=400, detail="account is not active")
        return row
    row = await accounts_repo.pick_least_recently_used(db)
    if not row:
        raise HTTPException(status_code=400, detail="No active Qwen accounts configured")
    return row

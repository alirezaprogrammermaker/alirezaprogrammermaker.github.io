from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class AccountCreate(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=256)
    name: Optional[str] = Field(None, min_length=1, max_length=64)


class AccountOut(BaseModel):
    id: str
    name: str
    email: str
    status: str
    last_used_at: Optional[int] = None
    created_at: int
    updated_at: int

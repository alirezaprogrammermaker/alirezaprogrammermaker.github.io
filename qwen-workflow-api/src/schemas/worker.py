from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ClaimRequest(BaseModel):
    worker_id: str = Field(..., min_length=1, max_length=128)


class CompleteRequest(BaseModel):
    status: str  # succeeded|failed
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    qwen_chat_id: Optional[str] = None
    assistant_content: Optional[str] = None

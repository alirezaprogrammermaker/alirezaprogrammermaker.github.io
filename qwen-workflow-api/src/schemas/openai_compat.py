from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompletionCreate(BaseModel):
    """OpenAI-compatible chat create + Qwen extensions."""

    model: str = "qwen-text"
    messages: list[ChatMessage] = Field(..., min_length=1)
    # Continuity: if set, resume that chat with its bound account
    chat_id: Optional[str] = None
    # Optional override (ignored if chat_id already bound to another account)
    account_id: Optional[str] = None
    think: Optional[Literal["auto", "think", "fast"]] = "auto"
    stream: bool = False  # not supported yet; rejected if true


class ImageCreate(BaseModel):
    model: str = "qwen-image"
    prompt: str = Field(..., min_length=1)
    chat_id: Optional[str] = None
    account_id: Optional[str] = None
    n: int = 1
    size: Optional[str] = None


class VideoCreate(BaseModel):
    model: str = "qwen-video"
    prompt: str = Field(..., min_length=1)
    chat_id: Optional[str] = None
    account_id: Optional[str] = None


class JobStatusOut(BaseModel):
    id: str
    object: str = "qwen.job"
    created: int
    model: Optional[str] = None
    status: str
    kind: str
    chat_id: Optional[str] = None
    account_id: Optional[str] = None
    qwen_chat_id: Optional[str] = None
    choices: list[dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None
    result: Optional[dict[str, Any]] = None

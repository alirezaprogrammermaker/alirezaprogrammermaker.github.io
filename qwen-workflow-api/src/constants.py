"""Shared constants — keep magic strings in one place."""

KIND_TEXT = "text"
KIND_IMAGE = "image"
KIND_VIDEO = "video"
KINDS = (KIND_TEXT, KIND_IMAGE, KIND_VIDEO)

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"

ACCOUNT_ACTIVE = "active"
ACCOUNT_DISABLED = "disabled"
ACCOUNT_INVALID = "invalid"

# OpenAI-style model aliases → internal kind
MODEL_KIND = {
    "qwen-text": KIND_TEXT,
    "qwen-chat": KIND_TEXT,
    "text": KIND_TEXT,
    "gpt-4o-mini": KIND_TEXT,  # alias for drop-in clients
    "qwen-image": KIND_IMAGE,
    "image": KIND_IMAGE,
    "dall-e-3": KIND_IMAGE,
    "qwen-video": KIND_VIDEO,
    "video": KIND_VIDEO,
}

LEASE_SECONDS = 15 * 60
CLEANUP_DAYS = 30
CLEANUP_BATCH = 400  # keep each cron invocation light (CPU + D1)

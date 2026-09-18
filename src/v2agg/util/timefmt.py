from __future__ import annotations

from datetime import datetime, timezone


def format_activity_label(when: datetime | None = None) -> str:
    """Short activity stamp for channel description updates."""
    dt = when or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

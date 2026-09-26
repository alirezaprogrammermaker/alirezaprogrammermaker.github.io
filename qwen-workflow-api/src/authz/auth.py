from __future__ import annotations

import hmac
from fastapi import Header, HTTPException, Request


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip()


async def require_api_key(
    request: Request,
    authorization: str | None = Header(default=None),
) -> str:
    env = request.scope["env"]
    token = _extract_bearer(authorization)
    expected = getattr(env, "API_KEY", None)
    if not expected or not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return token


async def require_worker_key(
    request: Request,
    authorization: str | None = Header(default=None),
) -> str:
    env = request.scope["env"]
    token = _extract_bearer(authorization)
    expected = getattr(env, "WORKER_KEY", None)
    if not expected or not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid worker key")
    return token

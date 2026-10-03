from __future__ import annotations

from fastapi import Request


def get_env(request: Request):
    return request.scope["env"]


def get_db(request: Request):
    return request.scope["env"].DB

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from authz.auth import require_api_key
from schemas.accounts import AccountCreate, AccountOut
from services import accounts as accounts_service

router = APIRouter(prefix="/v1/accounts", tags=["accounts"])


@router.post("", response_model=AccountOut, dependencies=[Depends(require_api_key)])
async def create_account(body: AccountCreate, request: Request):
    row = await accounts_service.add_account(
        request.scope["env"],
        email=body.email,
        password=body.password,
        name=body.name,
    )
    return row


@router.get("", dependencies=[Depends(require_api_key)])
async def list_accounts(request: Request):
    return await accounts_service.list_accounts(request.scope["env"])

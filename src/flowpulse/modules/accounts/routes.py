"""账号中心 API：/api/v1/accounts（统一列表 / 平台元数据 / 体检 / managed CRUD）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from flowpulse.modules.accounts.service import AccountService

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"])


def get_account_service() -> AccountService:
    raise RuntimeError("Dependency override is not configured")


class ManagedAccountCreate(BaseModel):
    platform: str = Field(min_length=1, max_length=32)
    account_key: str = Field(min_length=1, max_length=64)
    name: str = Field(default="", max_length=255)
    credential: str = Field(default="", max_length=65536)


class ManagedAccountUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    status: str | None = Field(default=None, max_length=32)


@router.get("")
def list_accounts(
    platform: str | None = None, service: AccountService = Depends(get_account_service)
) -> dict:
    return {"accounts": service.list_accounts(platform)}


@router.get("/platforms")
def list_platforms(service: AccountService = Depends(get_account_service)) -> dict:
    return {"platforms": service.platforms()}


@router.post("", status_code=201)
def create_account(
    request: ManagedAccountCreate, service: AccountService = Depends(get_account_service)
) -> dict:
    try:
        account = service.create_managed(
            request.platform,
            request.account_key.strip(),
            request.name.strip() or request.account_key.strip(),
            credential=request.credential,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return account


@router.patch("/{account_id}")
def update_account(
    account_id: int,
    request: ManagedAccountUpdate,
    service: AccountService = Depends(get_account_service),
) -> dict:
    try:
        return service.update_managed(account_id, request.name, request.status)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{account_id}/check")
async def check_account(
    account_id: int, service: AccountService = Depends(get_account_service)
) -> dict:
    try:
        return await service.check_account(account_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{account_id}")
async def delete_account(
    account_id: int, service: AccountService = Depends(get_account_service)
) -> dict:
    try:
        return await service.delete_account(account_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

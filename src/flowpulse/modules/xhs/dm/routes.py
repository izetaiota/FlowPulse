"""小红书私信 API（T4.1/T4.2）：会话/历史只读同步 + 规则 CRUD + 审核草稿。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from flowpulse.modules.xhs.dm.rules import DmRuleStore
from flowpulse.modules.xhs.dm.service import XhsDmService

router = APIRouter(prefix="/api/v1/xhs/dm", tags=["xhs-dm"])


def get_dm_service() -> XhsDmService:
    raise RuntimeError("Dependency override is not configured")


def get_dm_rule_store() -> DmRuleStore:
    raise RuntimeError("Dependency override is not configured")


class RuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    keywords: str = Field(min_length=1, max_length=500)  # 逗号分隔，命中任一即匹配
    reply_template: str = Field(min_length=1, max_length=2000)
    enabled: bool = True


class RuleUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    keywords: str | None = Field(default=None, max_length=500)
    reply_template: str | None = Field(default=None, max_length=2000)
    enabled: bool | None = None


# ---- 会话与历史（T4.1） ----


@router.get("/conversations")
async def list_conversations(
    pages: int = 1, service: XhsDmService = Depends(get_dm_service)
) -> dict:
    try:
        return await service.conversations(pages=max(1, min(5, pages)))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/conversations/{conv_id}/messages")
async def conversation_messages(
    conv_id: str,
    peer_uid: str = "",
    last_id: int = 0,
    count: int = 50,
    service: XhsDmService = Depends(get_dm_service),
) -> dict:
    try:
        return await service.history(
            conv_id, peer_uid=peer_uid, last_id=last_id, count=max(1, min(100, count))
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---- 规则（T4.2） ----


@router.get("/rules")
def list_rules(store: DmRuleStore = Depends(get_dm_rule_store)) -> dict:
    return {"rules": store.list_rules()}


@router.post("/rules", status_code=201)
def create_rule(
    request: RuleCreate, store: DmRuleStore = Depends(get_dm_rule_store)
) -> dict:
    return store.create_rule(request.model_dump())


@router.patch("/rules/{rule_id}")
def update_rule(
    rule_id: int,
    request: RuleUpdate,
    store: DmRuleStore = Depends(get_dm_rule_store),
) -> dict:
    updated = store.update_rule(rule_id, request.model_dump(exclude_none=True))
    if updated is None:
        raise HTTPException(status_code=404, detail="规则不存在")
    return updated


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, store: DmRuleStore = Depends(get_dm_rule_store)) -> dict:
    if not store.delete_rule(rule_id):
        raise HTTPException(status_code=404, detail="规则不存在")
    return {"deleted": True}


# ---- 审核草稿（T4.2：批准后由人工或后续发送批次执行） ----


@router.get("/drafts")
def list_drafts(
    status: str | None = None, store: DmRuleStore = Depends(get_dm_rule_store)
) -> dict:
    return {"drafts": store.list_drafts(status)}


@router.post("/drafts/{draft_id}/review")
def review_draft(
    draft_id: int,
    decision: str,
    store: DmRuleStore = Depends(get_dm_rule_store),
) -> dict:
    if decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="decision 必须是 approved / rejected")
    updated = store.review_draft(draft_id, decision)
    if updated is None:
        raise HTTPException(status_code=404, detail="草稿不存在")
    return updated


@router.delete("/drafts/{draft_id}")
def delete_draft(draft_id: int, store: DmRuleStore = Depends(get_dm_rule_store)) -> dict:
    if not store.delete_draft(draft_id):
        raise HTTPException(status_code=404, detail="草稿不存在")
    return {"deleted": True}

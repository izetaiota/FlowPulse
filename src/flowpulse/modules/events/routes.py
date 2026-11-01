"""Webhook 事件中心 API（P6-T6.1）：订阅 CRUD / 事件列表 / 手动触发投递。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from flowpulse.modules.events import KNOWN_EVENT_TYPES, EventCenter

router = APIRouter(prefix="/api/v1/events", tags=["events"])


def get_event_center() -> EventCenter:
    raise RuntimeError("Dependency override is not configured")


class SubscriptionIn(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    secret: str = Field(default="", max_length=200)
    events: str = Field(default="", max_length=500)  # 逗号分隔；空 = 全部
    enabled: bool = True


@router.get("/subscriptions")
def list_subscriptions(center: EventCenter = Depends(get_event_center)) -> dict:
    return {"subscriptions": center.list_subscriptions(), "event_types": KNOWN_EVENT_TYPES}


@router.put("/subscriptions", status_code=201)
def upsert_subscription(
    request: SubscriptionIn, center: EventCenter = Depends(get_event_center)
) -> dict:
    try:
        return center.upsert_subscription(
            request.url.strip(), request.secret, request.events, request.enabled
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/subscriptions/{sub_id}")
def delete_subscription(
    sub_id: int, center: EventCenter = Depends(get_event_center)
) -> dict:
    if not center.delete_subscription(sub_id):
        raise HTTPException(status_code=404, detail="订阅不存在")
    return {"deleted": True}


@router.get("/events")
def list_events(
    limit: int = 50, center: EventCenter = Depends(get_event_center)
) -> dict:
    return {"events": center.list_events(min(limit, 200))}


@router.post("/dispatch")
async def dispatch(center: EventCenter = Depends(get_event_center)) -> dict:
    """手动触发一轮投递（后台每 15s 自动跑）。"""
    return await center.dispatch_pending()

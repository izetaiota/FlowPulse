"""抖音私信 API（T4.4）：会话快照 / 历史消息 / 实时 WS（SSE 桥接可选，V1 手动拉取）。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from flowpulse.modules.douyin.dm.service import DouyinDmService

router = APIRouter(prefix="/api/v1/douyin/dm", tags=["douyin-dm"])


def get_douyin_dm_service() -> DouyinDmService:
    raise RuntimeError("Dependency override is not configured")


@router.get("/conversations")
async def list_conversations(
    service: DouyinDmService = Depends(get_douyin_dm_service),
) -> dict:
    try:
        conversations = await service.conversations()
        service.remember_self_uid(conversations)
        return {"ok": not service.last_error, "conversations": conversations,
                "message": service.last_error or f"同步到 {len(conversations)} 个会话"}
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/conversations/{conv_id}/messages")
async def conversation_messages(
    conv_id: str,
    conv_short_id: str,
    conv_type: int = 1,
    cursor: int = 0,
    count: int = 50,
    service: DouyinDmService = Depends(get_douyin_dm_service),
) -> dict:
    try:
        parsed = await service.history(
            conv_id, conv_short_id, conv_type=conv_type, cursor=cursor,
            count=max(1, min(100, count)),
        )
        return {"ok": True, **parsed}
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class _WsBridge:
    """实时接收测试入口：收 N 条或超时返回（生产用常驻任务接入消息中心）。"""

    def __init__(self, service: DouyinDmService):
        self.service = service
        self.messages: list[dict] = []


@router.get("/receive/test")
async def receive_test(
    seconds: int = 15,
    service: DouyinDmService = Depends(get_douyin_dm_service),
) -> dict:
    """连 frontier WS 收 seconds 秒（默认 15），返回期间收到的新消息。"""
    bridge = _WsBridge(service)
    try:
        # 先拉一次会话快照拿 self_uid（device_id）
        conversations = await service.conversations()
        service.remember_self_uid(conversations)
        await service.receive(
            on_message=bridge.messages.append,
            stop_after=max(5, min(120, seconds)),
        )
        return {"ok": True, "received": bridge.messages,
                "message": f"监听 {seconds}s，收到 {len(bridge.messages)} 条"}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

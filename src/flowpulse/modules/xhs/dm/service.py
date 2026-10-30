"""小红书私信服务（T4.1/T4.2）：浏览器只读同步 + 回复规则匹配生成审核草稿。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from flowpulse.modules.browser import ProfileAllocator
from flowpulse.modules.browser import engine as browser_engine
from flowpulse.modules.xhs.dm import reader
from flowpulse.modules.xhs.dm.rules import DmRuleStore

SETTLE_MS = 2600


def _xhs_storage_state(cookie: str) -> dict | None:
    """xhs cookie 串 → playwright storage_state（挂 .xiaohongshu.com 域）。"""
    cookies = []
    for chunk in (cookie or "").split(";"):
        if "=" not in chunk:
            continue
        name, _, value = chunk.strip().partition("=")
        if name:
            cookies.append(
                {"name": name, "value": value, "domain": ".xiaohongshu.com", "path": "/"}
            )
    return {"cookies": cookies, "origins": []} if cookies else None


class XhsDmService:
    def __init__(self, xhs_service, profiles_root: Path, rule_store: DmRuleStore):
        self.xhs_service = xhs_service
        self.allocator = ProfileAllocator(profiles_root)
        self.rules = rule_store

    def _login_state(self) -> dict | None:
        try:
            cookie = self.xhs_service.cookies.get("pc")
        except Exception:  # noqa: BLE001
            cookie = None
        return _xhs_storage_state(cookie or "")

    async def _open_chat_page(self, headless: bool = True):
        storage = self._login_state()
        if storage is None:
            raise RuntimeError("小红书未登录：请先在「小红书工作台」扫码或导入 Cookie")
        context = await browser_engine.launch_persistent_context(
            self.allocator.allocate("xhs", "dm"), headless=headless, storage_state=storage
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(reader.CHAT_URL, wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_timeout(SETTLE_MS)
        return context, page

    # ---- 会话同步（T4.1） ----

    async def conversations(self, pages: int = 1, headless: bool = True) -> dict:
        context, page = await self._open_chat_page(headless=headless)
        try:
            items, error = await reader.fetch_conversations_in_page(page, pages=pages)
        finally:
            await context.close()
        if error:
            return {"ok": False, "message": error, "conversations": []}
        drafts_created = self.generate_drafts(items)
        return {
            "ok": True,
            "message": f"同步到 {len(items)} 个会话，生成 {drafts_created} 条待审核回复",
            "conversations": items,
            "drafts_created": drafts_created,
        }

    async def history(
        self, conv_id: str, peer_uid: str = "", last_id: int = 0, count: int = 50,
        headless: bool = True,
    ) -> dict:
        context, page = await self._open_chat_page(headless=headless)
        try:
            parsed, error = await reader.fetch_history_in_page(
                page, conv_id, peer_uid=peer_uid, last_id=last_id, count=count
            )
        finally:
            await context.close()
        if error:
            return {"ok": False, "message": error, "messages": []}
        return {"ok": True, **parsed}

    # ---- 规则匹配（T4.2：草稿需人工审核，实际发送后续批次接入） ----

    def generate_drafts(self, conversations: list[dict]) -> int:
        rules = [r for r in self.rules.list_rules() if r["enabled"]]
        if not rules:
            return 0
        created = 0
        for conv in conversations:
            if int(conv.get("unread_count") or 0) <= 0:
                continue
            text = (conv.get("last_text") or "").strip()
            if not text:
                continue
            for rule in rules:
                keywords = [k.strip() for k in rule["keywords"].replace("，", ",").split(",") if k.strip()]
                if not keywords or not any(k in text for k in keywords):
                    continue
                if self.rules.draft_exists(conv["conv_id"], text):
                    break
                self.rules.create_draft(
                    {
                        "conv_id": conv["conv_id"],
                        "peer_uid": conv.get("peer_uid", ""),
                        "peer_nickname": conv.get("peer_nickname", ""),
                        "last_text": text[:500],
                        "rule_id": rule["id"],
                        "rule_name": rule["name"],
                        "suggested_reply": rule["reply_template"][:2000],
                    }
                )
                created += 1
                break
        return created

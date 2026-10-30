# ported from creatorhub app/browser/xhs_dm.py (github.com/3441293738/creatorhub, no license)
# — direct reuse per project decision; 选择器从其 selector 库简化为通用兜底
"""小红书私信浏览器发送（T4.2 收尾）：exactly-once 提交语义。

核心语义移植自 creatorhub xhs_dm.py：
- 提交前记录"已存在消息气泡数"基线；
- 点击发送前标记 dispatch 分界（此后任何异常都是 write_uncertain，绝不重发）；
- 成功判定要"明确证据"：平台写接口 2xx 响应 JSON 判 accepted，或页面气泡数增加；
- 平台业务拒绝（success:false / code!=0）不算成功。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

_DM_WRITE_PATHS = (
    "/api/im/web/short_link/send_message",
    "/api/im/web/message/send",
    "/api/im/web/msg/send",
    "/api/im/web/chat/send",
    "/api/im/web/message/create",
    "/api/im/web/msg/create",
)

# 通用选择器兜底（原版为成体系的 selector 分组，这里取关键三类）
EDITOR_SEL = ['[contenteditable="true"]', ".chat-input [contenteditable]", "textarea"]
SUBMIT_TEXTS = ("发送", "发送(Send)", "Send")


def _is_xhs_dm_write_response(response: Any) -> bool:
    try:
        parsed = urlsplit(str(response.url or ""))
        host = str(parsed.hostname or "").lower()
        path = str(parsed.path or "").rstrip("/").lower()
        method = str(getattr(response.request, "method", "") or "").upper()
        status = int(response.status)
        return (
            (host == "xiaohongshu.com" or host.endswith(".xiaohongshu.com"))
            and method == "POST"
            and 200 <= status < 300
            and path in _DM_WRITE_PATHS
        )
    except Exception:  # noqa: BLE001
        return False


def payload_result(payload: Any) -> str:
    """平台响应 → accepted / rejected / unknown（纯函数，可单测）。"""
    if not isinstance(payload, dict):
        return "unknown"
    root_success = payload.get("success")
    data = payload.get("data")
    data_success = data.get("success") if isinstance(data, dict) else None
    if root_success is False or data_success is False:
        return "rejected"
    code_results: list[bool] = []
    for key in ("code", "result_code"):
        if key not in payload:
            continue
        value = payload[key]
        accepted_code = not isinstance(value, bool) and (
            value == 0 or str(value).strip() == "0"
        )
        code_results.append(accepted_code)
        if not accepted_code:
            return "rejected"
    if root_success is True or data_success is True or any(code_results):
        return "accepted"
    return "unknown"


async def _bubble_count(page: Any, text: str) -> int | None:
    """统计已渲染的消息气泡数（不把编辑器里的草稿算进去）。"""
    try:
        return max(
            0,
            int(
                await page.evaluate(
                    """value => [...document.querySelectorAll(
                      '[class*="bubble"] [contenteditable], [class*="bubble__text"], [class*="message-content"]')]
                      .filter(node => (node.textContent || '').trim() === value).length""",
                    text,
                )
            ),
        )
    except Exception:  # noqa: BLE001
        return None


async def _find_editor(page: Any):
    for sel in EDITOR_SEL:
        try:
            locator = page.locator(sel).first
            if await locator.is_visible():
                return locator
        except Exception:  # noqa: BLE001
            continue
    return None


async def _find_submit(page: Any):
    try:
        buttons = page.locator("button")
        count = await buttons.count()
    except Exception:  # noqa: BLE001
        return None
    for i in range(count):
        button = buttons.nth(i)
        try:
            if not await button.is_visible() or not await button.is_enabled():
                continue
            label = ((await button.inner_text()) or "").strip()
            if label in SUBMIT_TEXTS:
                return button
        except Exception:  # noqa: BLE001
            continue
    return None


async def send_dm_in_page(page: Any, text: str, *, timeout_seconds: int = 15) -> tuple[bool, str]:
    """在已打开的私信会话页里发送一条消息，返回 (成功, 说明)。"""
    text = str(text or "").strip()
    if not text:
        return False, "空内容"

    submitted = {"dispatched": False}
    evidence: dict[str, Any] = {"accepted": False, "business_rejected": False, "responses": []}

    def on_response(response) -> None:
        if submitted["dispatched"] and _is_xhs_dm_write_response(response):
            evidence["responses"].append(response)

    listener_installed = False
    try:
        editor = await _find_editor(page)
        if editor is None:
            return False, "未找到私信输入框（页面可能改版或会话未打开）"
        await editor.click()
        await page.keyboard.type(text)
        baseline = await _bubble_count(page, text)
        await page.wait_for_timeout(600)

        try:
            page.on("response", on_response)
            listener_installed = True
        except Exception:  # noqa: BLE001
            pass

        submit = await _find_submit(page)
        try:
            submitted["dispatched"] = True  # 分界：此后绝不重发
            if submit is not None:
                await submit.click()
            else:
                await editor.press("Enter")
        except Exception as exc:  # noqa: BLE001
            return False, f"write_uncertain:私信已提交但页面操作中断: {exc}"

        import asyncio

        attempts = max(2, min(60, max(1, int(timeout_seconds)) * 4))
        for _ in range(attempts):
            # 证据一：平台写接口明确 accepted
            while evidence["responses"]:
                response = evidence["responses"].pop(0)
                try:
                    result = payload_result(await response.json())
                except Exception:  # noqa: BLE001
                    result = "unknown"
                if result == "accepted":
                    return True, ""
                if result == "rejected":
                    evidence["business_rejected"] = True
            # 证据二：页面气泡数增加
            current = await _bubble_count(page, text)
            if baseline is not None and current is not None and current > baseline:
                return True, ""
            try:
                if page.is_closed():
                    break
            except Exception:  # noqa: BLE001
                break
            await asyncio.sleep(0.3)

        detail = (
            "平台返回了业务拒绝结果，但提交状态仍需核对"
            if evidence["business_rejected"]
            else "私信已提交一次，但未取得明确成功证据"
        )
        return False, f"write_uncertain:{detail}，请到小红书核对"
    except Exception as exc:  # noqa: BLE001
        if submitted["dispatched"]:
            return False, f"write_uncertain:私信提交后页面异常: {exc}"
        return False, f"私信页面异常: {exc}"
    finally:
        if listener_installed:
            try:
                page.remove_listener("response", on_response)
            except Exception:  # noqa: BLE001
                pass

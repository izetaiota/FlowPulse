"""抖音发布浏览器驱动（T3.4）：创作中心上传页自动化。

流程移植自 creatorhub publish.py（直接沿用决策）：选择器多级兜底、风控人工验证
窗口（最长 5 分钟留给用户完成短信/扫码/滑块）、诊断截图落 data/debug/。
适配点：用本项目 browser.engine（ManagedContext）替代其 BrowserManager。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from flowpulse.modules.browser import engine as browser_engine

UPLOAD_URL = "https://creator.douyin.com/creator-micro/content/upload"
IMAGE_URL = "https://creator.douyin.com/creator-micro/content/upload?default-tab=3"

_TAB_IMAGE = ['div:has-text("发布图文")', 'text=发布图文', 'text=图文']
_TITLE_SEL = [
    'input[placeholder*="填写作品标题"]', 'input[placeholder*="作品标题"]',
    'input[placeholder*="标题"]', '.title-input input', 'input.semi-input',
]
_DESC_SEL = [
    '.editor-kit-editor-container [contenteditable="true"]',
    'div[data-placeholder*="简介"]', 'div[data-placeholder*="作品"]',
    'div[contenteditable="true"]', '.zone-container',
    'textarea[placeholder*="简介"]', 'textarea',
]
_PUBLISH_BTN = [
    'button:has-text("发布")', 'button:has-text("发布作品")',
    'div[class*="content-confirm"] button', '.publish-btn button',
]

_SUCCESS_KW = ("发布成功", "作品发布成功", "投稿成功", "发布完成", "已发布", "审核中")
_VERIFY_KW = (
    "接收短信验证码", "短信验证码", "为确保是本人操作", "输入验证码",
    "安全验证", "完成验证", "拖动滑块", "使用原设备扫码", "身份验证",
)

DEBUG_DIR = Path("./data/debug")


async def _visible_any(page, keywords) -> str:
    for kw in keywords:
        try:
            if await page.get_by_text(kw, exact=False).first.is_visible():
                return kw
        except Exception:  # noqa: BLE001
            continue
    return ""


async def _dump(page, tag: str) -> str:
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = DEBUG_DIR / f"dy_publish_{tag}_{stamp}"
        png = ""
        try:
            png = str(base.with_suffix(".png"))
            await page.screenshot(path=png, full_page=True)
        except Exception:  # noqa: BLE001
            png = ""
        try:
            text = await page.inner_text("body")
        except Exception:  # noqa: BLE001
            text = ""
        base.with_suffix(".txt").write_text(f"url: {page.url}\n\n{text[:4000]}", encoding="utf-8")
        return png
    except Exception:  # noqa: BLE001
        return ""


async def _click_first(page, selectors, timeout=2500) -> bool:
    for sel in selectors:
        try:
            await page.click(sel, timeout=timeout)
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


async def _fill_first(page, selectors, text, timeout=3000) -> bool:
    for sel in selectors:
        try:
            el = page.locator(sel).first
            await el.wait_for(state="visible", timeout=timeout)
            await el.click(timeout=timeout)
            try:
                await el.fill(text, timeout=timeout)
            except Exception:  # noqa: BLE001 - contenteditable fill 不支持时退回键入
                await page.keyboard.type(text)
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


async def _wait_editor(page, timeout_ms: int) -> bool:
    for sel in _DESC_SEL:
        try:
            await page.locator(sel).first.wait_for(state="visible", timeout=timeout_ms)
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


async def _primary_publish_button(page):
    """挑最终「发布」按钮：文本恰为发布类、可见、可用；取最后一个（表单底部）。"""
    try:
        buttons = page.locator("button")
        count = await buttons.count()
    except Exception:  # noqa: BLE001
        return None
    candidate = None
    for i in range(count):
        button = buttons.nth(i)
        try:
            if not await button.is_visible():
                continue
            text = ((await button.inner_text()) or "").strip()
            if text in ("发布", "发布作品", "发布视频", "发布图文"):
                candidate = button
        except Exception:  # noqa: BLE001
            continue
    return candidate


async def _choose_radio(page, label: str) -> bool:
    """安全精确地点单选项：先 role=radio，再 Semi 组件内文本恰等项；绝不 force/乱点祖先。"""
    try:
        loc = page.get_by_role("radio", name=label, exact=True)
        if await loc.count():
            await loc.first.scroll_into_view_if_needed(timeout=2000)
            try:
                await loc.first.check(timeout=2500)
            except Exception:  # noqa: BLE001
                await loc.first.click(timeout=2500)
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        radios = page.locator('label.semi-radio, .semi-radio, label[class*="radio"]')
        count = await radios.count()
        for i in range(count):
            radio = radios.nth(i)
            try:
                text = ((await radio.inner_text()) or "").strip()
            except Exception:  # noqa: BLE001
                continue
            if text == label:
                await radio.scroll_into_view_if_needed(timeout=2000)
                await radio.click(timeout=2000)
                return True
    except Exception:  # noqa: BLE001
        pass
    return False


async def _apply_publish_settings(page, visibility: str, allow_save: bool) -> None:
    vis_label = {"friends": "好友可见", "private": "仅自己可见"}.get(visibility, "")
    if vis_label:  # public 是默认值，不动
        await _choose_radio(page, vis_label)
    if not allow_save:  # 「允许」是默认值，只在「不允许」时点
        await _choose_radio(page, "不允许")


async def publish_douyin_video(
    storage_state: dict | None,
    profile_dir: Path,
    files: list[str],
    title: str,
    desc: str,
    visibility: str = "public",
    allow_save: bool = True,
    timeout_seconds: int = 300,
) -> tuple[bool, str, str]:
    """发布一条抖音作品（视频/图文）。返回 (ok, result_url, error)。

    必须有头（headed）：抖音风控人工验证（短信/扫码/滑块）需要用户在弹出的窗口里手动完成。
    """
    valid = [str(Path(p)) for p in files if p and Path(p).exists()]
    if not valid:
        return False, "", "没有可用的本地媒体文件（路径不存在）"

    context = await browser_engine.launch_persistent_context(
        profile_dir, headless=False, storage_state=storage_state
    )
    page = context.pages[0] if context.pages else await context.new_page()
    ok, result_url, error = False, "", ""
    try:
        url = IMAGE_URL if "image" in str(files[0]).lower() or files[0].endswith((".jpg", ".png", ".webp", ".gif")) else UPLOAD_URL
        await page.goto(url, wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_timeout(3000)
        if "passport" in page.url or "/login" in page.url:
            await _dump(page, "loggedout")
            return False, "", "logged_out: 抖音创作平台未登录，请先在「作品监控」页完成抖音扫码登录"

        try:
            await page.locator('input[type="file"]').first.set_input_files(valid[:9], timeout=15000)
        except Exception as exc:  # noqa: BLE001
            await _dump(page, "nofileinput")
            return False, "", f"上传文件失败（未找到文件输入框）：{exc}"

        if not await _wait_editor(page, 120000):
            await _dump(page, "noeditor")
            return False, "", "上传后未进入编辑页（视频可能仍在转码或上传失败），诊断截图已存 data/debug/"
        await page.wait_for_timeout(1500)

        if title:
            await _fill_first(page, _TITLE_SEL, title.strip()[:30])
            await page.wait_for_timeout(400)
        if desc:
            await _fill_first(page, _DESC_SEL, desc[:2000])
        await page.wait_for_timeout(800)

        await _apply_publish_settings(page, visibility, allow_save)
        await page.wait_for_timeout(600)

        button = None
        for _ in range(45):
            button = await _primary_publish_button(page)
            if button is not None:
                try:
                    if await button.is_enabled():
                        break
                except Exception:  # noqa: BLE001
                    break
            await page.wait_for_timeout(2000)
        if button is None:
            await _dump(page, "nobtn")
            return False, "", "未找到发布按钮（发布页可能改版），诊断截图已存 data/debug/"
        try:
            await button.scroll_into_view_if_needed(timeout=3000)
        except Exception:  # noqa: BLE001
            pass
        try:
            await button.click(timeout=5000)
        except Exception:  # noqa: BLE001
            if not await _click_first(page, _PUBLISH_BTN, timeout=4000):
                await _dump(page, "clickfail")
                return False, "", "发布按钮点击失败（可能被弹层遮挡/需补封面），诊断截图已存 data/debug/"

        # 成功判定 + 风控人工验证等待（窗口留给用户手动完成，最多 timeout_seconds）
        deadline = max(int(timeout_seconds), 300)
        waited, verify_notified = 0, False
        while waited < deadline:
            if "/content/manage" in page.url:
                ok = True
                break
            hit = await _visible_any(page, _SUCCESS_KW)
            if hit:
                ok = True
                break
            verify_hit = await _visible_any(page, _VERIFY_KW)
            if verify_hit and not verify_notified:
                verify_notified = True
                await _dump(page, "verify")
            await page.wait_for_timeout(2000)
            waited += 2
        result_url = page.url if ok else ""
        if not ok:
            if verify_notified:
                error = (
                    "发布被抖音风控拦下，需人工验证（短信验证码/扫码/滑块），"
                    "但在等待时间内未完成；请在弹窗完成验证后重新发布。"
                )
            else:
                await _dump(page, "unconfirmed")
                error = "已点发布但未确认到成功信号；请到抖音创作平台「作品管理」核实是否已发布。"
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        try:
            await _dump(page, "exception")
        except Exception:  # noqa: BLE001
            pass
        error = f"发布异常：{exc}"
    finally:
        try:
            await context.close()
        except Exception:  # noqa: BLE001
            pass
    return ok, result_url, error

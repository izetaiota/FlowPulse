"""微信读书通道可行性验证脚本（公众号订阅 RSS · 阶段 0 / T0.2）。

目的：在正式开发 `src/weread/` 采集模块前，用最小代价验证「微信读书 Web 接口
采集公众号文章」这条路在你的账号上确实跑得通：

  Cookie → cover 接口拉最新文章 → 还原 `~`→`_` 拼原文链接 → 链接可打开

2026-10-27 实测结论（对齐 we-mp-rss docs/weread-mp.md 与本机验证）：
  - 新版微信读书已废弃 /web/mp/articles 列表接口（恒返回 -2041），书架 sync
    里也不再返回公众号（MP_WXS_）条目；
  - 唯一可用采集路径：GET /api/mp/cover?bookId=<MP_WXS_xxx>，一次只返回
    该公众号最新一篇（reviewId + 标题 + 封面），增量靠轮询 + reviewId 去重；
  - 全文：GET /web/mp/content?reviewId=...（本脚本不拉正文）；
  - 无历史文章回补能力。

接口细节参考 rachelos/we-mp-rss（MIT）：
  - 书架:        GET /web/shelf/sync?userVid=&synckey=0&lectureSynckey=0
                 （userVid 必须传空字符串，非空反而触发 -2012）
  - 最新一篇:    GET /api/mp/cover?bookId=<MP_WXS_xxx>
  - 业务码:      -2012 Cookie 失效 / -2010、-2041 需重新扫码 / 200013 频率限制

使用步骤（先完成 T0.1）：
  1. 浏览器登录 https://weread.qq.com；
  2. F12 → Network → 任选一个 weread.qq.com 请求 → Request Headers →
     复制完整 Cookie 值（以 wr_vid=... 开头的一整串）；
  3. 把 Cookie 存入 scripts/weread_cookie.txt（已被 .gitignore，不会入库），
     或用环境变量 WEREAD_COOKIE，或命令行 --cookie；
  4. 运行（二选一）:
       python scripts/weread_probe.py --book-id MP_WXS_3012726261   # 直接验证指定公众号
       python scripts/weread_probe.py                               # 自动扫书架（旧版账号适用）

退出码：0=验证通过  1=配置缺失  2=登录态失效  3=通道异常
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path
from urllib.parse import quote

import httpx

WEREAD_BASE = "https://weread.qq.com"
MP_PREFIX = "MP_WXS_"
DEFAULT_COOKIE_FILE = Path(__file__).resolve().parent / "weread_cookie.txt"

# 与微信读书网页端一致的浏览器 UA（微信侧会校验 UA 合理性）
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 错误码 → 处置提示
ERR_CODE_GUIDE = {
    -2010: "需重新扫码登录（-2010）",
    -2012: "Cookie 已失效（-2012），请重新复制 Cookie",
    -2014: "账号配额耗尽（-2014）",
    -2041: "需重新扫码登录（-2041）",
    200013: "触发频率限制（200013），请稍后再试",
}


class ProbeError(Exception):
    """带业务码的探针错误。"""

    def __init__(self, code: int | str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def load_cookie(explicit: str | None, cookie_file: Path) -> str:
    """Cookie 来源优先级：--cookie > 环境变量 WEREAD_COOKIE > cookie 文件。"""
    if explicit:
        return explicit.strip()
    env = os.environ.get("WEREAD_COOKIE", "").strip()
    if env:
        return env
    if cookie_file.exists():
        return cookie_file.read_text(encoding="utf-8").strip()
    return ""


def build_headers(cookie: str) -> dict:
    """微信读书 web 域请求头（对齐 we-mp-rss 的 _weread_headers）。"""
    return {
        "Cookie": cookie,
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Origin": WEREAD_BASE,
        "Referer": f"{WEREAD_BASE}/",
    }


def raise_if_business_error(payload: dict) -> None:
    """微信读书把业务错误放在 HTTP 200 里（errCode/errcode）。"""
    code = payload.get("errCode", payload.get("errcode", 0))
    try:
        code = int(code or 0)
    except (TypeError, ValueError):
        code = 0
    if code == 0:
        return
    hint = ERR_CODE_GUIDE.get(code, "未知业务错误")
    fatal = code in (-2010, -2012, -2014, -2041)
    raise ProbeError(code, f"{hint}")


def weread_get(client: httpx.Client, path: str, params: dict) -> dict:
    resp = client.get(f"{WEREAD_BASE}{path}", params=params)
    if resp.status_code in (401, 499):
        raise ProbeError(resp.status_code, f"登录态失效或配额耗尽（HTTP {resp.status_code}）")
    if resp.status_code != 200:
        raise ProbeError(resp.status_code, f"HTTP {resp.status_code}: {path}")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise ProbeError("invalid_json", f"{path} 返回非 JSON") from exc
    raise_if_business_error(payload)
    return payload


def fetch_shelf(client: httpx.Client) -> list[dict]:
    """拉书架。注意 userVid 必须为空字符串。"""
    payload = weread_get(
        client,
        "/web/shelf/sync",
        {"userVid": "", "synckey": 0, "lectureSynckey": 0},
    )
    return payload.get("books", []) or []


def build_mp_url(original_id: str) -> str:
    """由文章 originalId（短链 token）拼公众号原文链接。

    微信读书把 token 里的 `_` 写成 `~`，必须还原，否则微信报「参数错误」
    （参考 we-mp-rss issue #467）。
    """
    token = str(original_id or "").strip().replace("~", "_")
    return f"https://mp.weixin.qq.com/s/{quote(token, safe='')}"


def link_from_review_id(review_id: str, book_id: str = "") -> str:
    """从 reviewId（MP_WXS_<bookId>_<token>）推导原文链接（cover 兜底用）。"""
    token = str(review_id or "").strip()
    prefix = f"{book_id}_" if book_id else ""
    if prefix and token.startswith(prefix):
        token = token[len(prefix):]
    elif "_" in token:
        token = token.split("_", 1)[1]
    return build_mp_url(token.replace("~", "_"))


def parse_articles(payload: dict) -> list[dict]:
    """解析 /web/mp/articles 的 groups → reviews → subReviews 结构。"""
    articles: list[dict] = []
    for group in payload.get("reviews", []) or []:
        group_time = group.get("createTime", 0)
        for sub in group.get("subReviews", []) or []:
            review = sub.get("review") or {}
            mp_info = review.get("mpInfo") or {}
            review_id = review.get("reviewId") or sub.get("reviewId")
            if not review_id:
                continue
            articles.append(
                {
                    "review_id": review_id,
                    "title": mp_info.get("title", "") or review.get("content", ""),
                    "link": build_mp_url(mp_info.get("originalId", "")),
                    "digest": (mp_info.get("content") or "")[:80],
                    "publish_time": int(mp_info.get("time") or review.get("createTime") or group_time or 0),
                }
            )
    return articles


def fetch_mp_articles(client: httpx.Client, book_id: str) -> list[dict]:
    """旧列表接口 /web/mp/articles（新版微信读书已废弃，预期 -2041，仅作尝试）。"""
    payload = weread_get(client, "/web/mp/articles", {"bookId": book_id, "offset": 0})
    return parse_articles(payload)


def fetch_mp_cover(client: httpx.Client, book_id: str) -> list[dict]:
    """新版主路径：/api/mp/cover 只返回最新一篇，增量靠轮询 + reviewId 去重。"""
    payload = weread_get(client, "/api/mp/cover", {"bookId": book_id})
    review_id = payload.get("reviewId", "")
    if not review_id:
        return []
    return [
        {
            "review_id": review_id,
            "title": payload.get("title", ""),
            "link": link_from_review_id(review_id, book_id),
            "digest": "[cover 兜底，仅最新一篇]",
            "publish_time": 0,
        }
    ]


def verify_mp_link(client: httpx.Client, url: str) -> str:
    """验证原文链接可打开（HTTP 200 且像微信文章页）。"""
    resp = client.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
    if resp.status_code != 200:
        return f"HTTP {resp.status_code}"
    text = resp.text
    if "js_content" in text or "msg_title" in text or "wechat" in text.lower():
        return "OK"
    return f"HTTP 200 但页面内容异常（长度 {len(text)}）"


def fmt_time(ts: int) -> str:
    if ts <= 0:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def main() -> int:
    parser = argparse.ArgumentParser(description="微信读书通道可行性验证（阶段 0）")
    parser.add_argument("--cookie", help="微信读书 Cookie 字符串")
    parser.add_argument(
        "--cookie-file",
        type=Path,
        default=DEFAULT_COOKIE_FILE,
        help=f"Cookie 文件路径（默认 {DEFAULT_COOKIE_FILE}）",
    )
    parser.add_argument("--max-mps", type=int, default=3, help="最多验证几个公众号（默认 3）")
    parser.add_argument("--book-id", help="直接指定公众号 bookId（如 MP_WXS_3012726261）验证")
    parser.add_argument("--skip-verify", action="store_true", help="跳过原文链接可达性验证")
    args = parser.parse_args()

    cookie = load_cookie(args.cookie, args.cookie_file)
    if not cookie:
        print("[配置缺失] 未找到微信读书 Cookie。请按脚本头部说明：")
        print(f"  1) 浏览器登录 {WEREAD_BASE} 并订阅公众号")
        print("  2) F12 → Network → 复制任一请求的完整 Cookie")
        print(f"  3) 存入 {args.cookie_file}（已 gitignore）或设置环境变量 WEREAD_COOKIE")
        return 1

    print(f"[1/5] 读取 Cookie：{cookie[:40]}...（长度 {len(cookie)}）")
    with httpx.Client(
        headers=build_headers(cookie),
        timeout=httpx.Timeout(15, read=30),
        follow_redirects=True,
    ) as client:
        if args.book_id:
            print(f"[2/5] 跳过书架，直接验证指定公众号：{args.book_id}")
            targets = [{"bookId": args.book_id, "title": args.book_id}]
        else:
            print("[2/5] 拉取书架（GET /web/shelf/sync）...")
            try:
                books = fetch_shelf(client)
            except ProbeError as exc:
                print(f"[失败] 书架拉取失败：{exc.message}")
                return 2
            print(f"      书架共 {len(books)} 本（含公众号订阅）")

            mp_books = [b for b in books if str(b.get("bookId", "")).startswith(MP_PREFIX)]
            print(f"[3/5] 识别公众号订阅：{len(mp_books)} 个（bookId 以 {MP_PREFIX} 开头）")
            if not mp_books:
                print("      书架里没有公众号条目（新版微信读书已不在书架返回公众号）。")
                print("      请用 --book-id MP_WXS_xxxxxxx 直接指定公众号验证；")
                print("      bookId 可从手机微信读书 App 公众号主页「复制链接」获得。")
                return 3
            for b in mp_books:
                print(f"      - {b.get('title', '(未命名)')}  bookId={b.get('bookId')}")

            targets = mp_books[: max(1, args.max_mps)]
        all_ok = True
        print(f"[4/5] 拉取文章列表（前 {len(targets)} 个公众号）...")
        for i, book in enumerate(targets, 1):
            book_id = str(book["bookId"])
            title = book.get("title", "(未命名)")
            try:
                articles = fetch_mp_articles(client, book_id)
                source = "articles"
            except ProbeError as exc:
                print(f"      [{i}/{len(targets)}] {title} 列表接口失败（{exc.message}），尝试 cover 兜底...")
                try:
                    articles = fetch_mp_cover(client, book_id)
                    source = "cover"
                except ProbeError as exc2:
                    print(f"      [{i}/{len(targets)}] {title} 兜底也失败：{exc2.message}")
                    all_ok = False
                    continue
            time.sleep(random.uniform(2, 4))  # 轻限速，避免触发频率限制
            print(f"      [{i}/{len(targets)}] {title}（{source}）拉到 {len(articles)} 篇：")
            for art in articles[:5]:
                print(
                    f"        · [{fmt_time(art['publish_time'])}] {art['title'][:40]}"
                    f"\n            {art['link']}"
                )

        print("[5/5] 验证原文链接可达性...")
        first_link = next(
            (a["link"] for a in articles if a.get("link")),
            None,
        ) if articles else None
        if args.skip_verify:
            print("      已跳过（--skip-verify）")
        elif not first_link:
            print("      没有可验证的链接")
            all_ok = False
        else:
            result = verify_mp_link(client, first_link)
            print(f"      {first_link}\n      → {result}")
            if result != "OK":
                all_ok = False

    print()
    if all_ok:
        print("✅ 验证通过：微信读书通道在你的账号上可用，可以进入阶段 1 正式开发。")
        return 0
    print("⚠️ 部分环节失败，请根据上方错误提示处理后重试。")
    return 3


if __name__ == "__main__":
    sys.exit(main())

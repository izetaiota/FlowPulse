"""Webhook 通知：多渠道（飞书 / 钉钉 / 自定义）推送，同 key 告警带冷却防轰炸。

渠道来源两层合并（去重）：
  - 环境变量（WEREAD_WEBHOOK_URL / WEREAD_NOTIFY_CHANNELS）
  - 页面管理的渠道库（NotifyStore 注入，运行时可增删）
每次发送按渠道记录日志（store 注入时），供设置页查看最近推送。
"""

import hashlib
import time

import httpx


class WebhookNotifier:
    def __init__(self, client: httpx.AsyncClient, webhook_urls: str | list[str], store=None):
        if isinstance(webhook_urls, str):
            raw = webhook_urls.replace("，", ",").split(",")
        else:
            raw = [str(u) for u in webhook_urls]
        # 去重保序，丢弃空串
        self._env_urls = [u for u in dict.fromkeys(u.strip() for u in raw) if u]
        self._client = client
        self._store = store
        self._last_sent: dict[str, float] = {}

    def _all_urls(self) -> list[str]:
        urls = list(self._env_urls)
        if self._store is not None:
            try:
                urls.extend(self._store.list_enabled_urls())
            except Exception:  # noqa: BLE001 - 渠道库异常不影响发送
                pass
        return [u for u in dict.fromkeys(u.strip() for u in urls) if u]

    @property
    def configured(self) -> bool:
        return bool(self._all_urls())

    def _payload(self, url: str, title: str, message: str) -> dict:
        if "oapi.dingtalk.com" in url:
            return {
                "msgtype": "markdown",
                "markdown": {"title": title, "text": f"**{title}**\n\n{message}"},
            }
        if "open.feishu.cn" in url:
            return {"msg_type": "text", "content": {"text": f"{title}\n{message}"}}
        return {"title": title, "text": message}

    def _image_payload(self, url: str, title: str, message: str, image_base64: str) -> dict:
        """飞书支持 image 消息（base64 + md5）；钉钉 markdown 不支持内联图，退文本。"""
        if "open.feishu.cn" in url:
            md5 = hashlib.md5(image_base64.encode("ascii")).hexdigest()
            return {"msg_type": "image", "image": {"base64": image_base64, "md5": md5}}
        return self._payload(url, title, message)

    async def _post_each(self, key: str, title: str, payload_for) -> bool:
        """逐渠道发送（payload_for(url) 决定该渠道的消息体），记录日志。"""
        sent_any = False
        now = time.monotonic()
        for url in self._all_urls():
            ok = False
            detail = ""
            try:
                response = await self._client.post(url, json=payload_for(url), timeout=10)
                ok = 200 <= response.status_code < 300
                detail = "" if ok else f"HTTP {response.status_code}"
            except httpx.HTTPError as exc:
                detail = str(exc)[:120]
            if self._store is not None:
                try:
                    self._store.add_log(url, key, title, ok, detail)
                except Exception:  # noqa: BLE001 - 日志失败不影响发送
                    pass
            sent_any = sent_any or ok
        if sent_any:
            self._last_sent[key] = now
        return sent_any

    async def send(
        self, key: str, title: str, message: str, cooldown_seconds: int = 3600
    ) -> bool:
        """发送告警；同一 key 在冷却期内只发一次。返回是否有渠道实际发出。"""
        if not self._all_urls():
            return False
        now = time.monotonic()
        if cooldown_seconds > 0 and now - self._last_sent.get(key, 0.0) < cooldown_seconds:
            return False
        return await self._post_each(key, title, lambda url: self._payload(url, title, message))

    async def send_image(
        self,
        key: str,
        title: str,
        message: str,
        image_base64: str,
        cooldown_seconds: int = 3600,
    ) -> bool:
        """带图消息：飞书渠道发图，其余渠道退回文本。"""
        if not image_base64:
            return await self.send(key, title, message, cooldown_seconds)
        if not self._all_urls():
            return False
        now = time.monotonic()
        if cooldown_seconds > 0 and now - self._last_sent.get(key, 0.0) < cooldown_seconds:
            return False
        return await self._post_each(
            key, title, lambda url: self._image_payload(url, title, message, image_base64)
        )

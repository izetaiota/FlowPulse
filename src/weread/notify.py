"""Webhook 通知：Cookie 失效 / 同步异常告警推送到飞书、钉钉或自定义地址。"""

import time

import httpx


class WebhookNotifier:
    """按 URL 自动适配飞书 / 钉钉消息格式；同 key 告警带冷却时间防轰炸。"""

    def __init__(self, client: httpx.AsyncClient, webhook_url: str):
        self._client = client
        self._url = (webhook_url or "").strip()
        self._last_sent: dict[str, float] = {}

    @property
    def configured(self) -> bool:
        return bool(self._url)

    def _payload(self, title: str, message: str) -> dict:
        if "oapi.dingtalk.com" in self._url:
            return {
                "msgtype": "markdown",
                "markdown": {"title": title, "text": f"**{title}**\n\n{message}"},
            }
        if "open.feishu.cn" in self._url:
            return {"msg_type": "text", "content": {"text": f"{title}\n{message}"}}
        return {"title": title, "text": message}

    async def send(
        self, key: str, title: str, message: str, cooldown_seconds: int = 3600
    ) -> bool:
        """发送告警；同一 key 在冷却期内只发一次。返回是否实际发出。"""
        if not self._url:
            return False
        now = time.monotonic()
        if now - self._last_sent.get(key, 0.0) < cooldown_seconds:
            return False
        try:
            response = await self._client.post(
                self._url, json=self._payload(title, message), timeout=10
            )
        except httpx.HTTPError:
            return False
        if 200 <= response.status_code < 300:
            self._last_sent[key] = now
            return True
        return False

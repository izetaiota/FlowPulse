"""Webhook 通知：多渠道（飞书 / 钉钉 / 自定义）推送，同 key 告警带冷却防轰炸。"""

import hashlib
import time

import httpx


class WebhookNotifier:
    """按各 URL 自动适配飞书 / 钉钉消息格式；支持逗号分隔多个渠道地址。

    - send: 文本/markdown 告警，逐渠道发送，任一成功即记冷却
    - send_image: 飞书渠道发图片消息（如登录二维码），其余渠道退回文本
    """

    def __init__(self, client: httpx.AsyncClient, webhook_urls: str | list[str]):
        if isinstance(webhook_urls, str):
            raw = webhook_urls.replace("，", ",").split(",")
        else:
            raw = [str(u) for u in webhook_urls]
        # 去重保序，丢弃空串
        self._urls = [u for u in dict.fromkeys(u.strip() for u in raw) if u]
        self._client = client
        self._last_sent: dict[str, float] = {}

    @property
    def configured(self) -> bool:
        return bool(self._urls)

    def _payload(self, url: str, title: str, message: str) -> dict:
        if "oapi.dingtalk.com" in url:
            return {
                "msgtype": "markdown",
                "markdown": {"title": title, "text": f"**{title}**\n\n{message}"},
            }
        if "open.feishu.cn" in url:
            return {"msg_type": "text", "content": {"text": f"{title}\n{message}"}}
        return {"title": title, "text": message}

    def _image_payload(self, url: str, title: str, message: str, image_base64: str):
        """飞书支持 image 消息（base64 + md5）；钉钉 markdown 不支持内联图，退文本。"""
        if "open.feishu.cn" in url:
            md5 = hashlib.md5(image_base64.encode("ascii")).hexdigest()
            return {"msg_type": "image", "image": {"base64": image_base64, "md5": md5}}, None
        return self._payload(url, title, message), None

    async def send(
        self, key: str, title: str, message: str, cooldown_seconds: int = 3600
    ) -> bool:
        """发送告警；同一 key 在冷却期内只发一次。返回是否有渠道实际发出。"""
        if not self._urls:
            return False
        now = time.monotonic()
        if cooldown_seconds > 0 and now - self._last_sent.get(key, 0.0) < cooldown_seconds:
            return False
        sent = False
        for url in self._urls:
            try:
                response = await self._client.post(
                    url, json=self._payload(url, title, message), timeout=10
                )
            except httpx.HTTPError:
                continue
            if 200 <= response.status_code < 300:
                sent = True
        if sent:
            self._last_sent[key] = now
        return sent

    async def send_image(
        self,
        key: str,
        title: str,
        message: str,
        image_base64: str,
        cooldown_seconds: int = 3600,
    ) -> bool:
        """带图消息：飞书渠道发图，其余渠道退回文本。"""
        if not self._urls or not image_base64:
            return await self.send(key, title, message, cooldown_seconds)
        now = time.monotonic()
        if cooldown_seconds > 0 and now - self._last_sent.get(key, 0.0) < cooldown_seconds:
            return False
        sent = False
        for url in self._urls:
            payload, _ = self._image_payload(url, title, message, image_base64)
            try:
                response = await self._client.post(url, json=payload, timeout=10)
            except httpx.HTTPError:
                continue
            if 200 <= response.status_code < 300:
                sent = True
        if sent:
            self._last_sent[key] = now
        return sent

"""Creator-specific Chrome transport defaults."""

from __future__ import annotations

from flowpulse.modules.xhs.xhs_utils.xhs_core.http import BrowserHttpClient

CREATOR_IMPERSONATE = 'chrome146'
CREATOR_ACCEPT_ENCODING = 'gzip, deflate, br, zstd'
CREATOR_HTTP_VERSION = 'v2tls'


class CreatorHttpClient(BrowserHttpClient):
    """One reusable Chrome-impersonating Session per Creator Auth lifecycle."""

    def __init__(
        self,
        *,
        proxies: dict | None = None,
        impersonate: str = CREATOR_IMPERSONATE,
    ) -> None:
        super().__init__(
            proxies=proxies,
            impersonate=impersonate,
            accept_encoding=CREATOR_ACCEPT_ENCODING,
            http_version=CREATOR_HTTP_VERSION,
        )


__all__ = [
    'CREATOR_ACCEPT_ENCODING',
    'CREATOR_HTTP_VERSION',
    'CREATOR_IMPERSONATE',
    'CreatorHttpClient',
]

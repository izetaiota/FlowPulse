"""通用链接下载模块（P2）：分享文案抽链 + yt-dlp 任务化下载 + 媒体库文件 API。"""

from flowpulse.modules.downloader.routes import get_download_service, router
from flowpulse.modules.downloader.service import (
    DownloadService,
    DownloadStore,
    DownloadTask,
    extract_urls,
    source_hint,
    yt_dlp_available,
)

__all__ = [
    "DownloadService",
    "DownloadStore",
    "DownloadTask",
    "extract_urls",
    "get_download_service",
    "router",
    "source_hint",
    "yt_dlp_available",
]

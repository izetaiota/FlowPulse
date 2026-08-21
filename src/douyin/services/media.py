import asyncio
import ipaddress
import os
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx


async def download_media(
    client: httpx.AsyncClient,
    url: str,
    destination: Path,
    max_bytes: int,
) -> Path:
    ensure_public_http_url(url)
    temporary = destination.with_suffix(destination.suffix + ".part")
    total = 0
    try:
        headers = {"Referer": "https://www.douyin.com/"}
        async with client.stream("GET", url, headers=headers) as response:
            response.raise_for_status()
            content_length = int(response.headers.get("content-length", 0))
            if content_length > max_bytes:
                raise RuntimeError(f"Media exceeds configured limit of {max_bytes} bytes")
            with temporary.open("wb") as stream:
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise RuntimeError(f"Media exceeds configured limit of {max_bytes} bytes")
                    stream.write(chunk)
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


async def extract_audio(video_path: Path, audio_path: Path) -> Path:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(
            "FFmpeg was not found. Install FFmpeg on PATH, set FFMPEG_PATH, "
            "or place it at .tools/ffmpeg/bin/ffmpeg.exe."
        )
    process = await asyncio.create_subprocess_exec(
        ffmpeg,
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(audio_path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode:
        message = stderr.decode("utf-8", errors="replace")[-1000:]
        raise RuntimeError(f"FFmpeg failed: {message}")
    return audio_path


def find_ffmpeg() -> str | None:
    configured = os.getenv("FFMPEG_PATH")
    if configured and Path(configured).is_file():
        return configured

    discovered = shutil.which("ffmpeg")
    if discovered:
        return discovered

    executable = "ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg"
    bundled = Path(__file__).resolve().parents[3] / ".tools" / "ffmpeg" / "bin" / executable
    if bundled.is_file():
        return str(bundled)

    return None


def ffmpeg_available() -> bool:
    return find_ffmpeg() is not None


def ensure_public_http_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError("Media URL must use HTTP or HTTPS")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return
    if not address.is_global:
        raise RuntimeError("Media URL must not target a private or local address")

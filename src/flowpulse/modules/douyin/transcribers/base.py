from pathlib import Path
from typing import Protocol

from flowpulse.modules.douyin.models import Transcript


class Transcriber(Protocol):
    name: str

    async def probe(self) -> bool: ...

    async def transcribe(self, audio_path: Path) -> Transcript: ...

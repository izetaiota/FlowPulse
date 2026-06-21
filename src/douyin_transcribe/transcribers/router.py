from pathlib import Path

from douyin_transcribe.models import Transcript
from douyin_transcribe.transcribers.base import Transcriber


class TranscriberRouter:
    def __init__(self, transcribers: list[Transcriber]):
        self.transcribers = {item.name: item for item in transcribers}

    async def transcribe(self, audio_path: Path, requested: str) -> Transcript:
        names = (
            [name for name in self.transcribers if name != "mock"]
            if requested == "auto"
            else [requested]
        )
        errors: list[str] = []
        for name in names:
            transcriber = self.transcribers.get(name)
            if not transcriber:
                errors.append(f"{name}: unknown engine")
                continue
            try:
                if await transcriber.probe():
                    return await transcriber.transcribe(audio_path)
                errors.append(f"{name}: unavailable")
            except Exception as exc:
                errors.append(f"{name}: {exc}")
        raise RuntimeError("All transcribers failed: " + "; ".join(errors))

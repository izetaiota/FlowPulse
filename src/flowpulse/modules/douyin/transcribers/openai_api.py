from pathlib import Path

import httpx

from flowpulse.modules.douyin.models import Transcript, TranscriptSegment


class OpenAITranscriber:
    name = "openai"

    def __init__(self, client: httpx.AsyncClient, base_url: str, api_key: str, model: str):
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    async def probe(self) -> bool:
        return bool(self.base_url and self.api_key)

    async def transcribe(self, audio_path: Path) -> Transcript:
        with audio_path.open("rb") as stream:
            response = await self.client.post(
                f"{self.base_url}/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                data={"model": self.model, "response_format": "verbose_json"},
                files={"file": (audio_path.name, stream, "audio/wav")},
            )
        response.raise_for_status()
        data = response.json()
        segments = [
            TranscriptSegment(
                start_ms=int(item.get("start", 0) * 1000),
                end_ms=int(item.get("end", 0) * 1000),
                text=item.get("text", "").strip(),
            )
            for item in data.get("segments", [])
        ]
        return Transcript(
            engine=self.name,
            language=data.get("language"),
            text=data.get("text", ""),
            segments=segments,
        )

from pathlib import Path

from flowpulse.modules.douyin.models import Transcript, TranscriptSegment


class MockTranscriber:
    name = "mock"

    async def probe(self) -> bool:
        return True

    async def transcribe(self, audio_path: Path) -> Transcript:
        text = "Mock transcript generated for pipeline verification."
        return Transcript(
            engine=self.name,
            language="en",
            text=text,
            segments=[TranscriptSegment(start_ms=0, end_ms=3000, text=text)],
        )

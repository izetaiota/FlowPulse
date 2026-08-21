import asyncio
import re
from pathlib import Path

from douyin.models import Transcript, TranscriptSegment


class SenseVoiceTranscriber:
    name = "sensevoice"

    def __init__(self):
        self._model = None

    async def probe(self) -> bool:
        try:
            import funasr  # noqa: F401
        except ImportError:
            return False
        return True

    async def transcribe(self, audio_path: Path) -> Transcript:
        return await asyncio.to_thread(self._transcribe_sync, audio_path)

    def _transcribe_sync(self, audio_path: Path) -> Transcript:
        if self._model is None:
            from funasr import AutoModel

            self._model = AutoModel(
                model="iic/SenseVoiceSmall",
                vad_model="fsmn-vad",
                vad_kwargs={"max_single_segment_time": 30000},
                trust_remote_code=True,
            )
        result = self._model.generate(
            input=str(audio_path),
            cache={},
            language="auto",
            use_itn=True,
        )
        segments: list[TranscriptSegment] = []
        texts: list[str] = []
        for item in result or []:
            text = clean_text(item.get("text", ""))
            if text:
                texts.append(text)
            for sentence in item.get("sentence_info", []):
                sentence_text = clean_text(sentence.get("text", ""))
                if sentence_text:
                    segments.append(
                        TranscriptSegment(
                            start_ms=int(sentence.get("start", 0)),
                            end_ms=int(sentence.get("end", 0)),
                            text=sentence_text,
                        )
                    )
        return Transcript(engine=self.name, text="\n".join(texts), segments=segments)


def clean_text(value: str) -> str:
    return re.sub(r"<\|.*?\|>", "", value).strip()

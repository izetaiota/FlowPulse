import asyncio
import os
import sys
from pathlib import Path

from douyin.models import Transcript, TranscriptSegment


class WhisperTranscriber:
    name = "whisper"

    def __init__(
        self,
        model_name: str = "small",
        device: str = "cuda",
        compute_type: str = "float16",
        language: str | None = "zh",
    ):
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self._model = None
        self._active_device = device

    async def probe(self) -> bool:
        add_cuda_dll_directory()
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return False
        return True

    async def transcribe(self, audio_path: Path) -> Transcript:
        return await asyncio.to_thread(self._transcribe_sync, audio_path)

    def _transcribe_sync(self, audio_path: Path) -> Transcript:
        model = self._load_model()
        try:
            segments_iter, info = self._transcribe_with_model(model, audio_path)
        except Exception:
            if self._active_device == "cpu":
                raise
            self._model = None
            self.device = "cpu"
            self.compute_type = "int8"
            model = self._load_model()
            segments_iter, info = self._transcribe_with_model(model, audio_path)
        segments: list[TranscriptSegment] = []
        texts: list[str] = []
        for item in segments_iter:
            text = item.text.strip()
            if not text:
                continue
            texts.append(text)
            segments.append(
                TranscriptSegment(
                    start_ms=int(item.start * 1000),
                    end_ms=int(item.end * 1000),
                    text=text,
                )
            )
        return Transcript(
            engine=self.name,
            language=getattr(info, "language", self.language),
            text="\n".join(texts),
            segments=segments,
        )

    def _transcribe_with_model(self, model, audio_path: Path):
        return model.transcribe(
            str(audio_path),
            language=self.language,
            vad_filter=True,
        )

    def _load_model(self):
        if self._model is not None:
            return self._model

        from faster_whisper import WhisperModel

        add_cuda_dll_directory()
        try:
            self._model = WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type,
            )
            self._active_device = self.device
        except Exception:
            if self.device == "cpu":
                raise
            self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
            self._active_device = "cpu"
        return self._model


def add_cuda_dll_directory() -> None:
    if not sys.platform.startswith("win"):
        return
    cuda_bin = Path(__file__).resolve().parents[3] / ".tools" / "cuda" / "bin"
    if not cuda_bin.is_dir():
        return
    os.environ["PATH"] = str(cuda_bin) + os.pathsep + os.environ.get("PATH", "")
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(cuda_bin))

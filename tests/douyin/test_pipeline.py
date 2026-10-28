from pathlib import Path

import httpx

from flowpulse.modules.douyin.models import TaskRecord, TaskStatus, TranscribeRequest, VideoInfo
from flowpulse.modules.douyin.services.pipeline import PipelineService
from flowpulse.modules.douyin.storage.tasks import TaskRepository
from flowpulse.modules.douyin.transcribers.mock import MockTranscriber
from flowpulse.modules.douyin.transcribers.router import TranscriberRouter


class FakeResolver:
    async def resolve(self, input_text: str) -> VideoInfo:
        return VideoInfo(
            source_url=input_text,
            resolved_url=input_text,
            media_url="https://media.example/video.mp4",
            title="Pipeline test",
        )


class EmbeddedSubtitleResolver:
    async def resolve(self, input_text: str) -> VideoInfo:
        return VideoInfo(
            source_url=input_text,
            resolved_url=input_text,
            media_url="https://media.example/video.mp4",
            title="Embedded subtitles",
            raw={"video_text": [{"start_time": 0, "end_time": 1000, "text": "Native caption"}]},
        )


class FailingTranscriber:
    name = "failing"

    async def probe(self):
        return True

    async def transcribe(self, audio_path):
        raise RuntimeError("expected transcription failure")


async def test_pipeline_completes(tmp_path: Path, monkeypatch):
    async def fake_download(client, url, destination, max_bytes):
        destination.write_bytes(b"video")
        return destination

    async def fake_extract(video_path, audio_path):
        audio_path.write_bytes(b"audio")
        return audio_path

    monkeypatch.setattr("flowpulse.modules.douyin.services.pipeline.download_media", fake_download)
    monkeypatch.setattr("flowpulse.modules.douyin.services.pipeline.extract_audio", fake_extract)

    repository = TaskRepository(tmp_path)
    async with httpx.AsyncClient() as client:
        pipeline = PipelineService(
            repository,
            FakeResolver(),
            TranscriberRouter([MockTranscriber()]),
            client,
            1024,
        )
        task = repository.save(
            TaskRecord(
                id="11111111-1111-1111-1111-111111111111",
                request=TranscribeRequest(input="https://v.douyin.com/test/", engine="mock"),
            )
        )
        await pipeline.run(task.id)

    completed = repository.get(task.id)
    assert completed.status == TaskStatus.COMPLETED
    assert {item.name for item in completed.artifacts} == {
        "source.json",
        "transcript.json",
        "transcript.srt",
        "notes.md",
    }


async def test_pipeline_uses_embedded_subtitles_without_download(tmp_path: Path, monkeypatch):
    async def fail_download(*args, **kwargs):
        raise AssertionError("download should not run when embedded subtitles exist")

    monkeypatch.setattr("flowpulse.modules.douyin.services.pipeline.download_media", fail_download)

    repository = TaskRepository(tmp_path)
    async with httpx.AsyncClient() as client:
        pipeline = PipelineService(
            repository,
            EmbeddedSubtitleResolver(),
            TranscriberRouter([MockTranscriber()]),
            client,
            1024,
        )
        task = repository.save(
            TaskRecord(
                id="22222222-2222-2222-2222-222222222222",
                request=TranscribeRequest(input="https://v.douyin.com/test/", engine="mock"),
            )
        )
        await pipeline.run(task.id)

    completed = repository.get(task.id)
    assert completed.status == TaskStatus.COMPLETED
    transcript = (tmp_path / "tasks" / task.id / "transcript.srt").read_text(encoding="utf-8")
    assert "Native caption" in transcript


async def test_pipeline_cleans_temporary_media_after_failure(tmp_path: Path, monkeypatch):
    async def fake_download(client, url, destination, max_bytes):
        destination.write_bytes(b"video")
        return destination

    async def fake_extract(video_path, audio_path):
        audio_path.write_bytes(b"audio")
        return audio_path

    monkeypatch.setattr("flowpulse.modules.douyin.services.pipeline.download_media", fake_download)
    monkeypatch.setattr("flowpulse.modules.douyin.services.pipeline.extract_audio", fake_extract)

    repository = TaskRepository(tmp_path)
    async with httpx.AsyncClient() as client:
        pipeline = PipelineService(
            repository,
            FakeResolver(),
            TranscriberRouter([FailingTranscriber()]),
            client,
            1024,
        )
        task = repository.save(
            TaskRecord(
                id="33333333-3333-3333-3333-333333333333",
                request=TranscribeRequest(
                    input="https://v.douyin.com/test/",
                    engine="auto",
                ),
            )
        )
        await pipeline.run(task.id)

    completed = repository.get(task.id)
    task_dir = tmp_path / "tasks" / task.id
    assert completed.status == TaskStatus.FAILED
    assert (task_dir / "source.json").is_file()
    assert not (task_dir / "video.mp4").exists()
    assert not (task_dir / "audio.wav").exists()

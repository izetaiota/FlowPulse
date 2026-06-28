import asyncio
from uuid import uuid4

import httpx

from douyin_transcribe.models import TaskRecord, TaskStatus, TranscribeRequest
from douyin_transcribe.renderers.artifacts import render_artifacts, to_artifact
from douyin_transcribe.resolvers.router import ResolverRouter
from douyin_transcribe.services.embedded_subtitles import extract_embedded_transcript
from douyin_transcribe.services.media import download_media, extract_audio
from douyin_transcribe.storage.tasks import TaskRepository
from douyin_transcribe.transcribers.router import TranscriberRouter


class PipelineService:
    def __init__(
        self,
        repository: TaskRepository,
        resolver: ResolverRouter,
        transcriber: TranscriberRouter,
        client: httpx.AsyncClient,
        max_download_bytes: int,
    ):
        self.repository = repository
        self.resolver = resolver
        self.transcriber = transcriber
        self.client = client
        self.max_download_bytes = max_download_bytes
        self.running: set[asyncio.Task] = set()

    def create(self, request: TranscribeRequest) -> TaskRecord:
        if request.client_request_id:
            existing = self.repository.find_by_client_request_id(request.client_request_id)
            if existing:
                return existing
        task = self.repository.save(TaskRecord(id=str(uuid4()), request=request))
        self.enqueue(task.id)
        return task

    def enqueue(self, task_id: str) -> None:
        background = asyncio.create_task(self.run(task_id))
        self.running.add(background)
        background.add_done_callback(self.running.discard)

    async def run(self, task_id: str) -> None:
        task = self.repository.get(task_id)
        if not task:
            return
        directory = task.task_dir(self.repository.root.parent)
        video_path = None
        audio_path = None
        try:
            self.update(task, TaskStatus.RESOLVING, 10, "Resolving Douyin share page")
            video = await self.resolver.resolve(task.request.input)
            source_path = directory / "source.json"
            source_path.write_text(video.model_dump_json(indent=2), encoding="utf-8")

            embedded = extract_embedded_transcript(video)
            if embedded:
                self.update(task, TaskStatus.RENDERING, 90, "Rendering embedded subtitles")
                task.artifacts = render_artifacts(directory, video, embedded, task.request.formats)
                self.update(task, TaskStatus.COMPLETED, 100, "Completed")
                return

            self.update(task, TaskStatus.DOWNLOADING, 30, "Downloading video")
            video_path = await download_media(
                self.client, video.media_url, directory / "video.mp4", self.max_download_bytes
            )

            self.update(task, TaskStatus.EXTRACTING_AUDIO, 50, "Extracting audio")
            audio_path = await extract_audio(video_path, directory / "audio.wav")

            self.update(task, TaskStatus.TRANSCRIBING, 70, "Transcribing audio")
            transcript = await self.transcriber.transcribe(audio_path, task.request.engine)

            self.update(task, TaskStatus.RENDERING, 90, "Rendering artifacts")
            task.artifacts = render_artifacts(directory, video, transcript, task.request.formats)
            if task.request.keep_video:
                task.artifacts.append(to_artifact(video_path, "video/mp4"))

            self.update(task, TaskStatus.COMPLETED, 100, "Completed")
        except Exception as exc:
            task.error = str(exc)
            self.update(task, TaskStatus.FAILED, task.progress, "Failed")
        finally:
            if audio_path:
                audio_path.unlink(missing_ok=True)
            if video_path and not task.request.keep_video:
                video_path.unlink(missing_ok=True)

    def update(self, task: TaskRecord, status: TaskStatus, progress: int, message: str) -> None:
        task.status = status
        task.progress = progress
        task.message = message
        self.repository.save(task)

    def retry(self, task_id: str) -> TaskRecord | None:
        task = self.repository.get(task_id)
        if not task:
            return None
        task.status = TaskStatus.PENDING
        task.progress = 0
        task.message = "Pending retry"
        task.error = None
        task.artifacts = []
        self.repository.save(task)
        self.enqueue(task_id)
        return task

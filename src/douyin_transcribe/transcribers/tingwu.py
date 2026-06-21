import asyncio
import json
import time
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from douyin_transcribe.models import Transcript, TranscriptSegment


class TingwuTranscriber:
    name = "tingwu"

    def __init__(
        self,
        access_key_id: str,
        access_key_secret: str,
        app_key: str,
        oss_bucket: str,
        oss_endpoint: str,
        oss_prefix: str = "douyin-transcribe",
        region: str = "cn-beijing",
        language_hint: str = "cn",
        poll_interval_seconds: float = 5,
        timeout_seconds: float = 1800,
    ):
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.app_key = app_key
        self.oss_bucket = oss_bucket
        self.oss_endpoint = oss_endpoint
        self.oss_prefix = oss_prefix.strip("/")
        self.region = region
        self.language_hint = language_hint
        self.poll_interval_seconds = poll_interval_seconds
        self.timeout_seconds = timeout_seconds

    async def probe(self) -> bool:
        if not all(
            [
                self.access_key_id,
                self.access_key_secret,
                self.app_key,
                self.oss_bucket,
                self.oss_endpoint,
            ]
        ):
            return False
        try:
            import aliyunsdkcore  # noqa: F401
            import oss2  # noqa: F401
        except ImportError:
            return False
        return True

    async def transcribe(self, audio_path: Path) -> Transcript:
        return await asyncio.to_thread(self._transcribe_sync, audio_path)

    def _transcribe_sync(self, audio_path: Path) -> Transcript:
        file_url = self._upload_audio(audio_path)
        task_id = self._create_task(audio_path, file_url)
        result = self._wait_for_result(task_id)
        return transcript_from_tingwu_result(result)

    def _upload_audio(self, audio_path: Path) -> str:
        import oss2

        auth = oss2.Auth(self.access_key_id, self.access_key_secret)
        bucket = oss2.Bucket(auth, self.oss_endpoint, self.oss_bucket, connect_timeout=30)
        key = f"{self.oss_prefix}/{int(time.time())}-{audio_path.stem}{audio_path.suffix}"
        oss2.resumable_upload(bucket, key, str(audio_path), part_size=4 * 1024 * 1024)
        return bucket.sign_url("GET", key, 3600 * 24)

    def _client(self):
        from aliyunsdkcore.client import AcsClient

        return AcsClient(self.access_key_id, self.access_key_secret, self.region)

    def _create_task(self, audio_path: Path, file_url: str) -> str:
        from aliyunsdkcore.request import CommonRequest

        body = {
            "AppKey": self.app_key,
            "Input": {
                "SourceLanguage": self.language_hint,
                "FileUrl": file_url,
            },
            "Parameters": {
                "Transcription": {
                    "DiarizationEnabled": False,
                }
            },
        }
        request = CommonRequest()
        request.set_domain("tingwu.cn-beijing.aliyuncs.com")
        request.set_version("2023-09-30")
        request.set_protocol_type("https")
        request.set_method("PUT")
        request.set_uri_pattern("/openapi/tingwu/v2/tasks")
        request.add_query_param("type", "offline")
        request.add_header("Content-Type", "application/json")
        request.set_content(json.dumps(body, ensure_ascii=False).encode("utf-8"))

        response = json.loads(self._client().do_action_with_exception(request))
        task_id = get_path(response, "Data", "TaskId") or get_path(response, "TaskId")
        if not task_id:
            raise RuntimeError(f"Tingwu did not return TaskId for {audio_path.name}: {response}")
        return str(task_id)

    def _wait_for_result(self, task_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout_seconds
        last_response: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            response = self._get_task(task_id)
            last_response = response
            status = str(
                get_path(response, "Data", "TaskStatus")
                or get_path(response, "Data", "Status")
                or get_path(response, "TaskStatus")
                or ""
            )
            if status.upper() in {"COMPLETED", "SUCCESS", "SUCCEEDED"}:
                result_url = (
                    get_path(response, "Data", "Result", "Transcription")
                    or get_path(response, "Data", "Result", "TranscriptionUrl")
                    or get_path(response, "Data", "ResultUrl")
                )
                if not result_url:
                    return response
                with urlopen(str(result_url), timeout=60) as stream:
                    return json.loads(stream.read().decode("utf-8"))
            if status.upper() in {"FAILED", "ERROR"}:
                raise RuntimeError(f"Tingwu task failed: {response}")
            time.sleep(self.poll_interval_seconds)
        raise TimeoutError(f"Tingwu task timed out: {last_response}")

    def _get_task(self, task_id: str) -> dict[str, Any]:
        from aliyunsdkcore.request import CommonRequest

        request = CommonRequest()
        request.set_domain("tingwu.cn-beijing.aliyuncs.com")
        request.set_version("2023-09-30")
        request.set_protocol_type("https")
        request.set_method("GET")
        request.set_uri_pattern(f"/openapi/tingwu/v2/tasks/{task_id}")
        return json.loads(self._client().do_action_with_exception(request))


def transcript_from_tingwu_result(result: dict[str, Any]) -> Transcript:
    segments = normalize_segments(dedupe_segments(collect_segments(result)))
    text = "\n".join(segment.text for segment in segments) or collect_text(result)
    return Transcript(engine="tingwu", language=None, text=text, segments=segments)


def collect_segments(value: Any) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    if isinstance(value, dict):
        text = first_string(value, ("Text", "text", "Sentence", "sentence"))
        start = first_number(value, ("BeginTime", "StartTime", "begin_time", "start_time", "Start"))
        end = first_number(value, ("EndTime", "end_time", "StopTime", "stop_time", "End"))
        if text and (start is not None or end is not None):
            start_ms = normalize_time(start, 0)
            end_ms = normalize_time(end, start_ms + 3000)
            if end_ms <= start_ms:
                end_ms = start_ms + 3000
            segments.append(TranscriptSegment(start_ms=start_ms, end_ms=end_ms, text=text))
        for item in value.values():
            segments.extend(collect_segments(item))
    elif isinstance(value, list):
        for item in value:
            segments.extend(collect_segments(item))
    return segments


def collect_text(value: Any) -> str:
    texts: list[str] = []
    if isinstance(value, dict):
        text = first_string(value, ("Text", "text", "Transcription", "transcription"))
        if text:
            texts.append(text)
        for item in value.values():
            nested = collect_text(item)
            if nested:
                texts.append(nested)
    elif isinstance(value, list):
        for item in value:
            nested = collect_text(item)
            if nested:
                texts.append(nested)
    return "\n".join(dict.fromkeys(texts))


def first_string(value: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            return item.strip()
    return ""


def first_number(value: dict[str, Any], keys: tuple[str, ...]) -> int | float | None:
    for key in keys:
        item = value.get(key)
        if isinstance(item, (int, float)):
            return item
    return None


def normalize_time(value: int | float | None, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, float) and not value.is_integer():
        return int(value * 1000)
    return int(value)


def dedupe_segments(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    seen: set[tuple[int, int, str]] = set()
    result: list[TranscriptSegment] = []
    for segment in sorted(segments, key=lambda item: (item.start_ms, item.end_ms, item.text)):
        key = (segment.start_ms, segment.end_ms, segment.text)
        if key in seen:
            continue
        seen.add(key)
        result.append(segment)
    return result


def normalize_segments(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    if not should_merge_short_segments(segments):
        return segments
    return merge_short_segments(segments)


def should_merge_short_segments(segments: list[TranscriptSegment]) -> bool:
    if len(segments) < 3:
        return False
    short_count = sum(1 for item in segments if len(item.text) <= 8)
    return short_count / len(segments) >= 0.7


def merge_short_segments(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    if not segments:
        return []

    merged: list[TranscriptSegment] = []
    current: list[TranscriptSegment] = []

    for segment in segments:
        current.append(segment)
        text = "".join(item.text for item in current)
        duration = current[-1].end_ms - current[0].start_ms
        if should_flush_segment(text, duration):
            merged.append(
                TranscriptSegment(
                    start_ms=current[0].start_ms,
                    end_ms=current[-1].end_ms,
                    text=text,
                )
            )
            current = []

    if current:
        merged.append(
            TranscriptSegment(
                start_ms=current[0].start_ms,
                end_ms=current[-1].end_ms,
                text="".join(item.text for item in current),
            )
        )
    return merged


def should_flush_segment(text: str, duration_ms: int) -> bool:
    if text.endswith(("。", "！", "？", ".", "!", "?")):
        return True
    if text.endswith(("，", "；", "、", ",", ";")) and duration_ms >= 2500:
        return True
    return duration_ms >= 6000 or len(text) >= 48


def get_path(value: Any, *parts: str) -> Any:
    for part in parts:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value

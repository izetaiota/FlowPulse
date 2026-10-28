from pathlib import Path

from fastapi.testclient import TestClient

from flowpulse.config import Settings
from flowpulse.main import create_app
from flowpulse.modules.douyin.models import (
    TaskRecord,
    TaskStatus,
    TranscribeRequest,
    Transcript,
    TranscriptSegment,
    VideoInfo,
)
from flowpulse.modules.douyin.renderers.artifacts import render_artifacts


def test_live_health(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "flowpulse.main.get_settings",
        lambda: Settings(data_dir=tmp_path, transcribe_engine="mock"),
    )
    with TestClient(create_app()) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_missing_task(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "flowpulse.main.get_settings",
        lambda: Settings(data_dir=tmp_path, transcribe_engine="mock"),
    )
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/tasks/missing")
    assert response.status_code == 404


def test_rejects_path_traversal_task_id(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "flowpulse.main.get_settings",
        lambda: Settings(data_dir=tmp_path, transcribe_engine="mock"),
    )
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/tasks/not-a-uuid")
    assert response.status_code == 404


def test_capabilities_describes_available_features(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "flowpulse.main.get_settings",
        lambda: Settings(data_dir=tmp_path, transcribe_engine="mock"),
    )
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/capabilities")

    assert response.status_code == 200
    assert response.json()["api_version"] == "v1"
    assert response.json()["engines"]["mock"] is True
    assert response.json()["formats"] == ["json", "srt", "markdown"]


def test_create_task_is_idempotent(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "flowpulse.main.get_settings",
        lambda: Settings(data_dir=tmp_path, transcribe_engine="mock"),
    )
    request = {
        "input": "https://v.douyin.com/idempotent/",
        "engine": "mock",
        "client_request_id": "extension-request-1",
    }
    with TestClient(create_app()) as client:
        first = client.post("/api/v1/tasks/transcribe", json=request)
        second = client.post("/api/v1/tasks/transcribe", json=request)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["id"] == second.json()["id"]


def test_lists_tasks_and_returns_structured_result(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "flowpulse.main.get_settings",
        lambda: Settings(data_dir=tmp_path, transcribe_engine="mock"),
    )
    app = create_app()
    repository = app.state.repository
    task = repository.save(
        TaskRecord(
            id="44444444-4444-4444-4444-444444444444",
            request=TranscribeRequest(input="https://v.douyin.com/result/"),
            status=TaskStatus.COMPLETED,
            progress=100,
        )
    )
    video = VideoInfo(
        source_url=task.request.input,
        resolved_url=task.request.input,
        media_url="https://media.example/result.mp4",
        title="Structured result",
    )
    transcript = Transcript(
        engine="mock",
        language="zh",
        text="Result text",
        segments=[TranscriptSegment(start_ms=0, end_ms=1000, text="Result text")],
    )
    task.artifacts = render_artifacts(
        task.task_dir(tmp_path),
        video,
        transcript,
        task.request.formats,
    )
    repository.save(task)

    with TestClient(app) as client:
        task_list = client.get("/api/v1/tasks", params={"limit": 1})
        result = client.get(f"/api/v1/tasks/{task.id}/result")

    assert task_list.status_code == 200
    assert task_list.json()["items"][0]["id"] == task.id
    assert task_list.json()["items"][0]["title"] == "Structured result"
    assert result.status_code == 200
    assert result.json()["schema_version"] == 1
    assert result.json()["source"]["title"] == "Structured result"
    assert result.json()["transcript"]["text"] == "Result text"


def test_result_requires_completed_task(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "flowpulse.main.get_settings",
        lambda: Settings(data_dir=tmp_path, transcribe_engine="mock"),
    )
    app = create_app()
    task = app.state.repository.save(
        TaskRecord(
            id="55555555-5555-5555-5555-555555555555",
            request=TranscribeRequest(input="https://v.douyin.com/pending/"),
        )
    )

    with TestClient(app) as client:
        response = client.get(f"/api/v1/tasks/{task.id}/result")

    assert response.status_code == 409

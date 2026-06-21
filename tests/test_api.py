from pathlib import Path

from fastapi.testclient import TestClient

from douyin_transcribe.config import Settings
from douyin_transcribe.main import create_app


def test_live_health(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "douyin_transcribe.main.get_settings",
        lambda: Settings(data_dir=tmp_path, transcribe_engine="mock"),
    )
    with TestClient(create_app()) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_missing_task(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "douyin_transcribe.main.get_settings",
        lambda: Settings(data_dir=tmp_path, transcribe_engine="mock"),
    )
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/tasks/missing")
    assert response.status_code == 404


def test_rejects_path_traversal_task_id(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "douyin_transcribe.main.get_settings",
        lambda: Settings(data_dir=tmp_path, transcribe_engine="mock"),
    )
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/tasks/not-a-uuid")
    assert response.status_code == 404

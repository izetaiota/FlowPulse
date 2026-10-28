from pathlib import Path

from fastapi.testclient import TestClient

from flowpulse.config import Settings
from flowpulse.main import create_app


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(
        "flowpulse.main.get_settings",
        lambda: Settings(data_dir=tmp_path, transcribe_engine="mock"),
    )
    return TestClient(create_app())


def test_xhs_login_status_not_logged_in(tmp_path: Path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        response = client.get("/api/v1/xhs/login/status", params={"platform": "pc"})
    assert response.status_code == 200
    assert response.json()["logged_in"] is False


def test_xhs_search_without_login_degrades_gracefully(tmp_path: Path, monkeypatch):
    # Not logged in must not 500; the service guards and reports success=False.
    with _client(tmp_path, monkeypatch) as client:
        response = client.post("/api/v1/xhs/search", json={"query": "x", "require_num": 3})
    assert response.status_code == 200
    assert response.json()["success"] is False


def test_xhs_note_detail_without_login_degrades_gracefully(tmp_path: Path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        response = client.post("/api/v1/xhs/notes/detail", json={"url": "https://x"})
    assert response.status_code == 200
    assert response.json()["success"] is False


def test_xhs_jobs_list_empty_then_create(tmp_path: Path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        empty = client.get("/api/v1/xhs/jobs")
        assert empty.status_code == 200
        assert empty.json() == []

        created = client.post(
            "/api/v1/xhs/jobs",
            json={"type": "search", "save_choice": "excel", "query": "x", "require_num": 1},
        )
        assert created.status_code == 202
        body = created.json()
        assert body["type"] == "search"
        assert body["id"]

"""console CLI 测试：任务注册、入口行为与关键任务的退出码约定。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flowpulse.console import cli, tasks


def test_task_registry_complete() -> None:
    assert set(tasks.TASKS) == {
        "weread-sync",
        "weread-status",
        "weread-refresh-cookie",
        "xhs-check",
        "xhs-monitor-scan",
        "douyin-monitor-scan",
        "ks-monitor-scan",
        "tiktok-monitor-scan",
    }
    for spec in tasks.TASKS.values():
        assert spec.help  # help 文案非空，list 命令才有意义


def test_cli_list(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out
    for name in tasks.TASKS:
        assert name in out


def test_cli_unknown_task() -> None:
    assert cli.main(["no-such-task"]) == 2


def test_cli_requires_task() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([])


def _run_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[int, dict]:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("WEREAD_COOKIE", "")
    monkeypatch.setenv("WEREAD_SYNC_INTERVAL_MINUTES", "0")
    from flowpulse.config import get_settings

    get_settings.cache_clear()
    import io
    from contextlib import redirect_stdout

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = tasks.run_task("weread-status")
    get_settings.cache_clear()
    return code, json.loads(buffer.getvalue())


def test_weread_status_no_credential_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """无凭证：ok=False，退出码非 0（供 cron 判定异常）。"""
    code, payload = _run_status(tmp_path, monkeypatch)
    assert code == 1
    assert payload["task"] == "weread-status"
    assert payload["ok"] is False
    assert payload["credential"]["configured"] is False


def test_weread_status_with_credential_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """有凭证、无订阅：ok=True，退出码 0。"""
    from flowpulse.modules.weread.storage import WereadRepository

    WereadRepository(tmp_path).save_credential("wr_vid=1; wr_skey=x")
    code, payload = _run_status(tmp_path, monkeypatch)
    assert code == 0
    assert payload["ok"] is True
    assert payload["credential"]["configured"] is True


def test_weread_sync_exit_code_follows_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """weread-sync 复用 scheduler.run_once：error_count>0 时退出码非 0。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("WEREAD_SYNC_INTERVAL_MINUTES", "0")
    from flowpulse.config import get_settings

    get_settings.cache_clear()

    async def fake_run_once(self) -> dict:
        return {"ok_count": 1, "error_count": 2, "new_articles": 0}

    monkeypatch.setattr("flowpulse.modules.weread.scheduler.WereadScheduler.run_once", fake_run_once)
    import io
    from contextlib import redirect_stdout

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = tasks.run_task("weread-sync")
    get_settings.cache_clear()
    assert code == 1
    payload = json.loads(buffer.getvalue())
    assert payload["ok"] is False
    assert payload["error_count"] == 2

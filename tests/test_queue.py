"""统一任务队列视图测试：跨源合并排序、来源过滤、重试语义。"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from flowpulse.modules.douyin.models import TaskStatus
from flowpulse.modules.queue import QueueService
from flowpulse.modules.xhs.integration.models import JobStatus


def task_item(task_id: str, status: TaskStatus, minutes_ago: int = 0):
    ts = datetime(2026, 10, 30, 12, 0, 0) - timedelta(minutes=minutes_ago)
    return SimpleNamespace(
        id=task_id,
        title=f"任务 {task_id}",
        status=status,
        message="",
        error=None,
        created_at=ts,
        updated_at=ts,
    )


def xhs_job(job_id: str, status: JobStatus, minutes_ago: int = 0):
    from flowpulse.modules.xhs.integration.models import CreateJobRequest, JobRecord, JobType

    ts = datetime(2026, 10, 30, 12, 0, 0) - timedelta(minutes=minutes_ago)
    request = CreateJobRequest(type=JobType.NOTES, notes=["https://xhs.example/1"])
    return SimpleNamespace(
        id=job_id,
        type=SimpleNamespace(value="notes"),
        request=request,
        status=status,
        message="",
        error=None,
        created_at=ts,
        updated_at=ts,
    )


class StubTaskRepository:
    def __init__(self, items):
        self._items = items

    def list(self, limit=20, cursor=None):
        return self._items, None


class StubXhsJobs:
    def __init__(self, jobs):
        self._jobs = jobs

    def list(self):
        return self._jobs


class StubPipeline:
    def retry(self, task_id):
        if task_id == "missing":
            return None
        return SimpleNamespace(id=task_id, status="pending", message="已重新入队")


def test_queue_merges_and_sorts_by_updated_at():
    service = QueueService(
        StubTaskRepository([task_item("t1", TaskStatus.FAILED, minutes_ago=5)]),
        StubPipeline(),
        StubXhsJobs([xhs_job("j1", JobStatus.RUNNING, minutes_ago=1)]),
    )
    items = service.list()
    assert [i["id"] for i in items] == ["j1", "t1"]  # 新的在前
    assert items[1]["retryable"] is True and items[0]["retryable"] is False
    assert {i["source"] for i in items} == {"douyin", "xhs"}


def test_queue_filter_by_source():
    service = QueueService(
        StubTaskRepository([task_item("t1", TaskStatus.COMPLETED)]),
        StubPipeline(),
        StubXhsJobs([xhs_job("j1", JobStatus.COMPLETED)]),
    )
    assert [i["source"] for i in service.list(source="douyin")] == ["douyin"]
    assert [i["source"] for i in service.list(source="xhs")] == ["xhs"]


def test_queue_retry_semantics():
    service = QueueService(StubTaskRepository([]), StubPipeline(), StubXhsJobs([]))
    result = service.retry("douyin", "t9")
    assert result["status"] == "pending"
    with pytest.raises(ValueError):
        service.retry("xhs", "j1")  # xhs 任务暂不支持重试
    with pytest.raises(KeyError):
        service.retry("douyin", "missing")

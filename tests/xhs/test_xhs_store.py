from pathlib import Path

from xhs_spider.integration.models import CreateJobRequest, JobRecord, JobType
from xhs_spider.integration.store import CookieStore, JobRepository


def test_cookie_store_roundtrip(tmp_path: Path):
    store = CookieStore(tmp_path)
    assert store.get("pc") is None

    store.set("pc", "a1=1; web_session=2")
    store.set("creator", "x=1")
    assert store.get("pc") == "a1=1; web_session=2"
    assert store.get("creator") == "x=1"

    store.clear("pc")
    assert store.get("pc") is None
    assert store.get("creator") == "x=1"


def test_job_repository_save_get_list(tmp_path: Path):
    repo = JobRepository(tmp_path)
    assert repo.list() == []
    assert repo.get("missing") is None

    record = JobRecord(
        id="job1",
        type=JobType.SEARCH,
        request=CreateJobRequest(type=JobType.SEARCH, query="x"),
    )
    repo.save(record)

    got = repo.get("job1")
    assert got is not None
    assert got.id == "job1"
    assert got.type == JobType.SEARCH
    assert [item.id for item in repo.list()] == ["job1"]

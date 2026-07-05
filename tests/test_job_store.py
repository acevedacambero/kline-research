from __future__ import annotations

import duckdb
import pytest

from kline.jobs.store import JobStatus, JobStore


def test_jobs_persist_with_detached_json_values(tmp_path):
    path = tmp_path / "jobs.duckdb"
    payload = {"symbols": ["000001"], "nested": {"limit": 3}}
    with JobStore(path) as store:
        job = store.create("download", payload, resumable=True)
        payload["symbols"].append("mutated")
        store.update_progress(job.id, {"done": 1})

    with JobStore(path) as reopened:
        saved = reopened.get(job.id)
        assert saved is not None
        assert saved.status is JobStatus.QUEUED
        assert saved.payload == {"symbols": ["000001"], "nested": {"limit": 3}}
        assert saved.progress == {"done": 1}
        saved.payload["symbols"].append("detached")
        assert reopened.get(job.id).payload["symbols"] == ["000001"]


def test_schema_version_and_configured_duckdb_settings(tmp_path):
    with JobStore(tmp_path / "jobs.duckdb", memory_limit="256MB", threads=1) as store:
        assert store.schema_version == 1
        assert store.connection.execute(
            "SELECT value FROM schema_metadata WHERE key = ?", ["schema_version"]
        ).fetchone() == ("1",)
        assert store.connection.execute(
            "SELECT current_setting('threads'), current_setting('memory_limit')"
        ).fetchone() == (1, "244.1 MiB")


@pytest.mark.parametrize("memory_limit", ["2GB; DROP TABLE jobs", "unlimited", "-1GB"])
def test_memory_limit_rejects_unsafe_values(tmp_path, memory_limit):
    with pytest.raises(ValueError):
        JobStore(tmp_path / "jobs.duckdb", memory_limit=memory_limit)


def test_threads_rejects_invalid_values(tmp_path):
    with pytest.raises(ValueError):
        JobStore(tmp_path / "jobs.duckdb", threads=0)


def test_transitions_completion_failure_and_listing(tmp_path):
    with JobStore(tmp_path / "jobs.duckdb") as store:
        first = store.create("download", {"n": 1})
        second = store.create("features", {"n": 2})
        running = store.transition(first.id, JobStatus.RUNNING)
        assert running.status is JobStatus.RUNNING
        completed = store.complete(first.id, {"rows": 4})
        assert completed.status is JobStatus.COMPLETED
        assert completed.result == {"rows": 4}
        failed = store.fail(second.id, "provider unavailable")
        assert failed.status is JobStatus.FAILED
        assert failed.error == "provider unavailable"
        assert [job.id for job in store.list(status=JobStatus.COMPLETED)] == [first.id]
        with pytest.raises(ValueError):
            store.transition(first.id, JobStatus.RUNNING)


def test_startup_recovery_interrupts_only_running_jobs(tmp_path):
    path = tmp_path / "jobs.duckdb"
    with JobStore(path) as store:
        queued = store.create("queued", {})
        running = store.create("running", {})
        completed = store.create("completed", {})
        store.transition(running.id, JobStatus.RUNNING)
        store.transition(completed.id, JobStatus.RUNNING)
        store.complete(completed.id, {"ok": True})

    with JobStore(path) as recovered:
        assert recovered.get(queued.id).status is JobStatus.QUEUED
        assert recovered.get(running.id).status is JobStatus.INTERRUPTED
        assert recovered.get(completed.id).status is JobStatus.COMPLETED


def test_closed_store_rejects_queries(tmp_path):
    store = JobStore(tmp_path / "jobs.duckdb")
    store.close()
    with pytest.raises(duckdb.ConnectionException):
        store.list()

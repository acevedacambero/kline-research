from __future__ import annotations

from datetime import date
from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pandas as pd
from fastapi.testclient import TestClient

import kline.api as api_module
from kline.api import create_app
from kline.config import Settings
from kline.data.pipeline import DatasetPipeline


class BlockingSource:
    def __init__(self, release: threading.Event):
        self.release = release

    def list_securities(self):
        return [{"exchange": "sh", "code": "600000", "name": "Bank"}]

    def stock_history(self, *args, **kwargs):
        return pd.DataFrame()

    def index_history(self, *args, **kwargs):
        return pd.DataFrame()

    def adjustment_factors(self, *args, **kwargs):
        return pd.DataFrame([{
            "date": date(1900, 1, 1), "qfq_factor": 1.0, "hfq_factor": 1.0,
        }])


def _wait_running(client: TestClient, task_id: str) -> None:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if client.get(f"/api/datasets/tasks/{task_id}").json()["status"] == "running":
            return
        time.sleep(0.01)
    raise AssertionError("import did not enter running state")


def test_import_blocks_label_and_feature_globally(tmp_path, monkeypatch):
    release = threading.Event()
    source = BlockingSource(release)

    def blocked_fetch(self, exchange, code, start, end):
        release.wait(timeout=3)
        raise RuntimeError("released")

    monkeypatch.setattr(api_module.HybridDownloadSource, "fetch_bundle", blocked_fetch)
    settings = Settings(data_path=tmp_path / "data", jobs_db_path=tmp_path / "jobs.duckdb")
    app = create_app(settings, source)
    try:
        with TestClient(app) as client:
            started = client.post("/api/datasets/import", json={"scope": "representative"})
            assert started.status_code == 202
            task_id = started.json()["taskId"]
            _wait_running(client, task_id)

            for path in ("/api/labels/build", "/api/features/build"):
                response = client.post(path, json={"scope": "all"})
                assert response.status_code == 409
                assert response.json()["detail"] == {
                    "code": "HEAVY_JOB_ALREADY_RUNNING",
                    "message": f"A heavy job is already running: {task_id}",
                    "taskId": task_id,
                }
    finally:
        release.set()


def test_import_writes_are_serial_on_one_coordinator_thread(tmp_path, monkeypatch):
    raw = pd.DataFrame([{
        "date": date(2024, 1, 2), "open": 10.0, "high": 11.0, "low": 9.0,
        "close": 10.5, "volume": 100, "amount": 1000,
    }])
    factors = pd.DataFrame([{"date": date(1900, 1, 1), "qfq_factor": 1.0, "hfq_factor": 1.0}])

    def fetch(self, exchange, code, start, end):
        return raw.copy(), factors.copy()

    monkeypatch.setattr(api_module.HybridDownloadSource, "fetch_bundle", fetch)
    active = 0
    maximum = 0
    writer_threads: set[int] = set()
    lock = threading.Lock()
    original = DatasetPipeline.import_security

    def instrumented(self, *args, **kwargs):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
            writer_threads.add(threading.get_ident())
        try:
            return original(self, *args, **kwargs)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(DatasetPipeline, "import_security", instrumented)
    app = create_app(
        Settings(data_path=tmp_path / "data", jobs_db_path=tmp_path / "jobs.duckdb"),
        BlockingSource(threading.Event()),
    )
    with TestClient(app) as client:
        started = client.post("/api/datasets/import", json={"scope": "representative"})
        task_id = started.json()["taskId"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            task = client.get(f"/api/datasets/tasks/{task_id}").json()
            if task["status"] not in {"queued", "running"}:
                break
            time.sleep(0.01)

        assert task["status"] == "completed"
        assert task["done"] == task["total"] == 3
        assert maximum == 1
        assert len(writer_threads) == 1
        assert app.state.heavy_coordinator.pending_count == 0
        assert not any(hasattr(value, "executor") for value in app.state.__dict__.values())


def test_durable_queued_import_status_preserves_ui_fields(tmp_path):
    app = create_app(
        Settings(data_path=tmp_path / "data", jobs_db_path=tmp_path / "jobs.duckdb"),
        BlockingSource(threading.Event()),
    )
    job = app.state.job_store.create("import", [{"exchange": "sh", "code": "600000"}])
    response = TestClient(app).get(f"/api/datasets/tasks/{job.id}")
    assert response.status_code == 200
    assert response.json() == {
        "id": job.id, "status": "queued", "total": 1, "done": 0, "rows": 0,
        "errors": [], "currentSecurity": None, "stage": "queued", "speed": 0.0,
        "etaSeconds": None, "directAvailable": None,
    }


def test_task_status_endpoints_are_scoped_by_job_type(tmp_path):
    app = create_app(
        Settings(data_path=tmp_path / "data", jobs_db_path=tmp_path / "jobs.duckdb"),
        BlockingSource(threading.Event()),
    )
    import_job = app.state.job_store.create("import", [])
    label_job = app.state.job_store.create("labels", [])
    client = TestClient(app)
    assert client.get(f"/api/labels/tasks/{import_job.id}").status_code == 404
    assert client.get(f"/api/features/tasks/{import_job.id}").status_code == 404
    assert client.get(f"/api/datasets/tasks/{label_job.id}").status_code == 404


def test_queued_import_status_persists_direct_availability(tmp_path, monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(
        api_module.HybridDownloadSource, "fetch_bundle",
        lambda self, *args: (release.wait(3), (_ for _ in ()).throw(RuntimeError("released")))[1],
    )
    app = create_app(
        Settings(data_path=tmp_path / "data", jobs_db_path=tmp_path / "jobs.duckdb"),
        BlockingSource(release),
    )
    try:
        with TestClient(app) as client:
            started = client.post("/api/datasets/import", json={"scope": "representative"})
            task = client.get(f'/api/datasets/tasks/{started.json()["taskId"]}').json()
            assert task["directAvailable"] is app.state.download_source.direct_available
    finally:
        release.set()


def test_lazy_bars_write_uses_coordinator_and_is_blocked_by_active_import(tmp_path, monkeypatch):
    release = threading.Event()
    source = BlockingSource(release)
    monkeypatch.setattr(api_module.HybridDownloadSource, "fetch_bundle",
                        lambda self, *args: release.wait(3) or (_ for _ in ()).throw(RuntimeError()))
    app = create_app(
        Settings(data_path=tmp_path / "data", jobs_db_path=tmp_path / "jobs.duckdb"), source
    )
    try:
        with TestClient(app) as client:
            started = client.post("/api/datasets/import", json={"scope": "representative"})
            _wait_running(client, started.json()["taskId"])
            response = client.get("/api/securities/sh/600000/bars")
            assert response.status_code == 409
            assert response.json()["detail"]["code"] == "HEAVY_JOB_ALREADY_RUNNING"
            assert response.json()["detail"]["taskId"] == started.json()["taskId"]
    finally:
        release.set()


def test_lazy_bars_cache_write_runs_on_heavy_worker(tmp_path, monkeypatch):
    rows = pd.DataFrame([{
        "date": date(2024, 1, 2), "open": 10.0, "high": 11.0, "low": 9.0,
        "close": 10.5, "volume": 100, "amount": 1000,
    }])
    source = BlockingSource(threading.Event())
    source.stock_history = lambda *args, **kwargs: rows
    writer_threads = []
    original = DatasetPipeline.import_security

    def instrumented(self, *args, **kwargs):
        writer_threads.append(threading.current_thread().name)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(DatasetPipeline, "import_security", instrumented)
    app = create_app(
        Settings(data_path=tmp_path / "data", jobs_db_path=tmp_path / "jobs.duckdb"), source
    )
    with TestClient(app) as client:
        response = client.get("/api/securities/sh/600000/bars")
        assert response.status_code == 200
        assert writer_threads == ["kline-heavy-job_0"]


def test_two_concurrent_lazy_cache_misses_follow_global_rejection_policy(tmp_path):
    entered = threading.Event()
    release = threading.Event()
    rows = pd.DataFrame([{
        "date": date(2024, 1, 2), "open": 10.0, "high": 11.0, "low": 9.0,
        "close": 10.5, "volume": 100, "amount": 1000,
    }])
    source = BlockingSource(release)

    def stock_history(*args, **kwargs):
        entered.set()
        release.wait(3)
        return rows

    source.stock_history = stock_history
    app = create_app(
        Settings(data_path=tmp_path / "data", jobs_db_path=tmp_path / "jobs.duckdb"), source
    )
    try:
        with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(client.get, "/api/securities/sh/600000/bars")
            assert entered.wait(2)
            second = client.get("/api/securities/sz/000001/bars")
            assert second.status_code == 409
            assert second.json()["detail"]["code"] == "HEAVY_JOB_ALREADY_RUNNING"
            release.set()
            assert first.result(timeout=3).status_code == 200
    finally:
        release.set()


def test_lazy_cache_fetch_failure_preserves_message_contract(tmp_path):
    source = BlockingSource(threading.Event())
    source.stock_history = lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("boom"))
    app = create_app(
        Settings(data_path=tmp_path / "data", jobs_db_path=tmp_path / "jobs.duckdb"), source
    )
    with TestClient(app) as client:
        response = client.get("/api/securities/sh/600000/bars")
        assert response.status_code == 503
        assert response.json()["detail"] == {
            "code": "AKSHARE_FETCH_FAILED", "message": "行情获取失败：boom"
        }


def test_lazy_cache_missing_output_preserves_message_contract(tmp_path, monkeypatch):
    rows = pd.DataFrame([{
        "date": date(2024, 1, 2), "open": 10.0, "high": 11.0, "low": 9.0,
        "close": 10.5, "volume": 100, "amount": 1000,
    }])
    source = BlockingSource(threading.Event())
    source.stock_history = lambda *args, **kwargs: rows
    monkeypatch.setattr(DatasetPipeline, "latest_derived_path", lambda *args: None)
    app = create_app(
        Settings(data_path=tmp_path / "data", jobs_db_path=tmp_path / "jobs.duckdb"), source
    )
    with TestClient(app) as client:
        response = client.get("/api/securities/sh/600000/bars")
        assert response.status_code == 500
        assert response.json()["detail"] == {
            "code": "CACHE_WRITE_FAILED", "message": "快照写入失败"
        }


def test_active_job_rejection_skips_all_provider_preprocessing(tmp_path, monkeypatch):
    release = threading.Event()
    source = BlockingSource(release)
    calls = 0

    def forbidden_list():
        nonlocal calls
        calls += 1
        raise AssertionError("provider preprocessing must not run")

    source.list_securities = forbidden_list
    monkeypatch.setattr(api_module.HybridDownloadSource, "fetch_bundle",
                        lambda self, *args: release.wait(3) or (_ for _ in ()).throw(RuntimeError()))
    app = create_app(
        Settings(data_path=tmp_path / "data", jobs_db_path=tmp_path / "jobs.duckdb"), source
    )
    try:
        with TestClient(app) as client:
            first = client.post("/api/datasets/import", json={"scope": "representative"})
            _wait_running(client, first.json()["taskId"])
            for path in ("/api/datasets/import", "/api/labels/build", "/api/features/build"):
                response = client.post(path, json={"scope": "all"})
                assert response.status_code == 409
                assert response.json()["detail"]["code"] == "HEAVY_JOB_ALREADY_RUNNING"
            assert calls == 0
    finally:
        release.set()


def test_hung_import_fetch_times_out_and_releases_coordinator(tmp_path, monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(api_module.HybridDownloadSource, "fetch_bundle",
                        lambda self, *args: release.wait(10))
    app = create_app(
        Settings(data_path=tmp_path / "data", jobs_db_path=tmp_path / "jobs.duckdb",
                 security_fetch_timeout_seconds=1),
        BlockingSource(release),
    )
    try:
        with TestClient(app) as client:
            started = client.post("/api/datasets/import", json={"scope": "representative"})
            task_id = started.json()["taskId"]
            deadline = time.monotonic() + 2.5
            while time.monotonic() < deadline:
                task = client.get(f"/api/datasets/tasks/{task_id}").json()
                if task["status"] not in {"queued", "running"}:
                    break
                time.sleep(0.02)
            assert task["status"] == "completed_with_errors"
            assert len(task["errors"]) == 3
            assert all("timed out after 1s" in error["message"] for error in task["errors"])
            follow_up = client.post("/api/features/build", json={"scope": "all"})
            assert follow_up.status_code == 202
    finally:
        release.set()


def test_hung_lazy_fetch_returns_timeout_and_releases_coordinator(tmp_path):
    release = threading.Event()
    source = BlockingSource(release)
    source.stock_history = lambda *args, **kwargs: release.wait(10)
    app = create_app(
        Settings(data_path=tmp_path / "data", jobs_db_path=tmp_path / "jobs.duckdb",
                 security_fetch_timeout_seconds=1), source
    )
    try:
        with TestClient(app) as client:
            started = time.monotonic()
            response = client.get("/api/securities/sh/600000/bars")
            assert time.monotonic() - started < 2.5
            assert response.status_code == 503
            assert response.json()["detail"] == {
                "code": "AKSHARE_FETCH_FAILED",
                "message": "行情获取失败：fetch timed out after 1s",
            }
            follow_up = client.post("/api/features/build", json={"scope": "all"})
            assert follow_up.status_code == 202
    finally:
        release.set()


def test_label_and_feature_jobs_use_only_shared_heavy_worker_and_no_pipeline_writes(
    tmp_path, monkeypatch
):
    pipeline_writes = []
    original = DatasetPipeline.import_security

    def instrumented(self, *args, **kwargs):
        pipeline_writes.append(threading.current_thread().name)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(DatasetPipeline, "import_security", instrumented)
    app = create_app(
        Settings(data_path=tmp_path / "data", jobs_db_path=tmp_path / "jobs.duckdb"),
        BlockingSource(threading.Event()),
    )
    with TestClient(app) as client:
        for start_path, status_prefix in (
            ("/api/labels/build", "/api/labels/tasks/"),
            ("/api/features/build", "/api/features/tasks/"),
        ):
            response = client.post(start_path, json={"scope": "all"})
            assert response.status_code == 202
            task_id = response.json()["taskId"]
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                task = client.get(status_prefix + task_id).json()
                if task["status"] not in {"queued", "running"}:
                    break
                time.sleep(0.01)
            assert task["status"] == "completed"

        worker_names = [thread.name for thread in threading.enumerate()]
        assert sum(name.startswith("kline-heavy-job") for name in worker_names) == 1
        assert not any(name.startswith(("label-build", "feature-build")) for name in worker_names)
        assert pipeline_writes == []

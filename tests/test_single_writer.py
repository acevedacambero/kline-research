from __future__ import annotations

from datetime import date
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

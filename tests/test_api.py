from datetime import date, timedelta
import time

import pandas as pd
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

import kline.api as api_module
from kline.api import create_app, dataframe_records
from kline.config import Settings
from kline.data.pipeline import DatasetPipeline


class FakeSource:
    def list_securities(self):
        return [{"exchange": "sh", "code": "600000", "name": "浦发银行"}]

    def stock_history(self, *args, **kwargs):
        return pd.DataFrame()

    def index_history(self, *args, **kwargs):
        return pd.DataFrame()

    def adjustment_factors(self, *args, **kwargs):
        return pd.DataFrame()

    def sina_raw_history(self, *args, **kwargs):
        raise AssertionError("provider must not be called")

    def sina_adjustment_factors(self, *args, **kwargs):
        raise AssertionError("provider must not be called")


def test_health_exposes_all_version_keys(tmp_path):
    app = create_app(Settings(data_path=tmp_path / "data"), FakeSource())
    response = TestClient(app).get("/api/system/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["dataSource"] == "AkShare"
    assert body["versions"]["labelDefinitionVersion"] == "daily-v1"
    assert body["versions"]["limitRuleVersion"] == "cn-equity-v1"


def test_validate_akshare_reports_available_securities(tmp_path):
    app = create_app(Settings(data_path=tmp_path / "data"), FakeSource())
    response = TestClient(app).post("/api/datasets/validate")
    assert response.status_code == 200
    assert response.json()["markets"]["sh"] == 1


def test_dataframe_records_converts_nan_to_json_null():
    frame = pd.DataFrame([{"date": "2024-01-02", "ma60": float("nan"), "close": 10.0}])
    assert dataframe_records(frame) == [{"date": "2024-01-02", "ma60": None, "close": 10.0}]


def seed_security(data_path):
    rows = []
    for index in range(260):
        close = 10 + index / 100
        rows.append({
            "date": date(2024, 1, 1) + timedelta(days=index),
            "open": close, "high": close + 0.1, "low": close - 0.1, "close": close,
            "volume": 1000 + index, "amount": 10000 + index,
        })
    factors = pd.DataFrame([{
        "date": date(1900, 1, 1), "qfq_factor": 1.0, "hfq_factor": 1.0,
    }])
    pipeline = DatasetPipeline(data_path)
    pipeline.initialize_catalog()
    pipeline.import_security("sh", "600000", pd.DataFrame(rows), factors)


def test_feature_build_task_and_point_in_time_audit(tmp_path):
    data_path = tmp_path / "data"
    seed_security(data_path)
    app = create_app(Settings(data_path=data_path), FakeSource())
    with TestClient(app) as client:
        started = client.post("/api/features/build", json={"scope": "all"})
        assert started.status_code == 202
        task_id = started.json()["taskId"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            task = client.get(f"/api/features/tasks/{task_id}").json()
            if task["status"] not in {"queued", "running"}:
                break
            time.sleep(0.02)
        assert task["status"] == "completed"
        assert task["rows"] == 260
        assert task["errors"] == []

        audited = client.post(
            "/api/p2/audit",
            json={"exchange": "sh", "code": "600000", "signal_date": "2024-09-16"},
        )
        assert audited.status_code == 200
        body = audited.json()
        assert set(body["groups"]) == {
            "trend", "position", "momentum", "volumePrice", "tradingBehavior"
        }
        assert body["versions"]["featureDefinitionVersion"] == "daily-features-v1"
        assert body["availableHistory"] == 260

        scored = client.post(
            "/api/p3/audit",
            json={"exchange": "sh", "code": "600000", "signal_date": "2024-09-16"},
        )
        assert scored.status_code == 200
        score_body = scored.json()
        assert score_body["versions"]["scoreDefinitionVersion"] == "p3-rule-score-v1"
        assert 0 <= score_body["score"]["score"] <= 100
        assert set(score_body["score"]["components"]) == {
            "trend", "position", "momentum", "volumePrice", "tradingBehavior"
        }
        assert score_body["featureDefinitionVersion"] == "daily-features-v1"


def test_score_build_task_is_pollable(tmp_path):
    data_path = tmp_path / "data"
    seed_security(data_path)
    app = create_app(Settings(data_path=data_path), FakeSource())
    with TestClient(app) as client:
        started = client.post("/api/scores/build", json={"scope": "all"})
        assert started.status_code == 202
        task_id = started.json()["taskId"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            task = client.get(f"/api/scores/tasks/{task_id}").json()
            if task["status"] not in {"queued", "running"}:
                break
            time.sleep(0.02)
        assert task["status"] == "completed"
        assert task["rows"] == 260
        assert task["errors"] == []


def test_score_task_unknown_id_is_404(tmp_path):
    app = create_app(Settings(data_path=tmp_path / "data"), FakeSource())
    response = TestClient(app).get("/api/scores/tasks/missing")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "TASK_NOT_FOUND"


def test_feature_task_unknown_id_is_404(tmp_path):
    app = create_app(Settings(data_path=tmp_path / "data"), FakeSource())
    response = TestClient(app).get("/api/features/tasks/missing")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "TASK_NOT_FOUND"


def test_settings_derive_jobs_database_beside_overridden_data_path(tmp_path):
    app = create_app(Settings(data_path=tmp_path / "custom-data"), FakeSource())
    assert app.state.jobs_db_path == tmp_path / "custom-data" / "jobs.duckdb"


class MixedMarketSource(FakeSource):
    def list_securities(self):
        return [
            {"exchange": "sh", "code": "600000", "name": "SH"},
            {"exchange": "sz", "code": "000001", "name": "SZ"},
            {"exchange": "bj", "code": "920001", "name": "BJ"},
        ]


def test_public_security_list_filters_beijing_market(tmp_path):
    app = create_app(Settings(data_path=tmp_path / "data"), MixedMarketSource())
    response = TestClient(app).get("/api/securities")
    assert response.status_code == 200
    assert {item["exchange"] for item in response.json()} == {"sh", "sz"}


def test_representative_import_contains_only_supported_markets(tmp_path):
    app = create_app(Settings(data_path=tmp_path / "data"), MixedMarketSource())
    with TestClient(app) as client:
        response = client.post("/api/datasets/import", json={"scope": "representative"})
    assert response.status_code == 202
    assert response.json()["requested"] == 2


def test_full_import_filters_beijing_market(tmp_path):
    app = create_app(Settings(data_path=tmp_path / "data"), MixedMarketSource())
    with TestClient(app) as client:
        response = client.post("/api/datasets/import", json={"scope": "all"})
    assert response.status_code == 202
    assert response.json()["requested"] == 2


def test_beijing_market_requests_are_rejected_before_data_access(tmp_path):
    app = create_app(Settings(data_path=tmp_path / "data"), MixedMarketSource())
    with TestClient(app) as client:
        responses = [
            client.get("/api/securities/bj/920001/bars"),
            client.post(
                "/api/p1/audit",
                json={"exchange": "bj", "code": "920001", "signal_date": "2024-01-02"},
            ),
            client.post(
                "/api/p2/audit",
                json={"exchange": "bj", "code": "920001", "signal_date": "2024-01-02"},
            ),
        ]
    assert [response.status_code for response in responses] == [422, 422, 422]
    assert all(
        response.json()["detail"]["code"] == "MARKET_NOT_SUPPORTED"
        for response in responses
    )


def test_history_backfill_api_starts_and_is_pollable(tmp_path):
    data_path = tmp_path / "data"
    pipeline = DatasetPipeline(data_path)
    pipeline.initialize_catalog()
    raw = pd.DataFrame(
        [{
            "date": date.today(), "open": 10.0, "high": 11.0, "low": 9.0,
            "close": 10.5, "volume": 100, "amount": 1000.0,
        }]
    )
    factors = pd.DataFrame(
        [{"date": date(1900, 1, 1), "qfq_factor": 1.0, "hfq_factor": 1.0}]
    )
    pipeline.import_security("sh", "600000", raw, factors)
    app = create_app(Settings(data_path=data_path), FakeSource())

    with TestClient(app) as client:
        started = client.post("/api/datasets/backfill-history")
        assert started.status_code == 202
        assert started.json()["threshold"] == 250
        assert started.json()["total"] == 1
        task_id = started.json()["taskId"]
        task = client.get(f"/api/datasets/backfill-history/{task_id}")

    assert task.status_code == 200
    assert {
        "status", "done", "total", "completed", "listingHistoryShort",
        "errors", "currentSecurity", "speed", "etaSeconds",
    }.issubset(task.json())


def test_history_backfill_unknown_task_is_404(tmp_path):
    app = create_app(Settings(data_path=tmp_path / "data"), FakeSource())
    response = TestClient(app).get("/api/datasets/backfill-history/missing")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "TASK_NOT_FOUND"


def test_history_backfill_start_alias_uses_same_contract(tmp_path):
    app = create_app(Settings(data_path=tmp_path / "data"), FakeSource())
    with TestClient(app) as client:
        response = client.post("/api/history-backfill", json={})
    assert response.status_code == 202
    assert response.json()["total"] == 0
    assert response.json()["threshold"] == 250


def test_history_backfill_can_start_through_import_command_bus(tmp_path):
    app = create_app(Settings(data_path=tmp_path / "data"), FakeSource())
    with TestClient(app) as client:
        response = client.post(
            "/api/datasets/import", json={"scope": "history_backfill"}
        )
    assert response.status_code == 202
    assert response.json()["total"] == 0
    assert response.json()["threshold"] == 250


def test_quality_reports_history_backfill_counts(tmp_path):
    app = create_app(Settings(data_path=tmp_path / "data"), FakeSource())
    response = TestClient(app).get("/api/datasets/quality")
    assert response.status_code == 200
    assert response.json()["shortHistoryCached"] == 0
    assert response.json()["listingHistoryShort"] == 0
    assert response.json()["historyBackfillFailed"] == 0


def test_quality_caches_expensive_short_history_scan(tmp_path, monkeypatch):
    calls = 0
    original = api_module.HistoryBackfillService.scan

    def counted_scan(self):
        nonlocal calls
        calls += 1
        return original(self)

    monkeypatch.setattr(api_module.HistoryBackfillService, "scan", counted_scan)
    app = create_app(Settings(data_path=tmp_path / "data"), FakeSource())
    with TestClient(app) as client:
        assert client.get("/api/datasets/quality").status_code == 200
        assert client.get("/api/datasets/quality").status_code == 200

    assert calls == 1


def test_history_backfill_settings_are_positive():
    assert Settings().history_backfill_min_days == 250
    with pytest.raises(ValidationError):
        Settings(history_backfill_min_days=0)

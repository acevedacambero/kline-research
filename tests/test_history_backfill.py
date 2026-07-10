from datetime import date, timedelta
from pathlib import Path
import threading
import time

import pandas as pd

import pytest

from kline.data.history_backfill import (
    BackfillCandidate,
    BackfillCoverageError,
    BackfillResult,
    HistoryBackfillService,
)
from kline.data.pipeline import DatasetPipeline
from kline.api import HistoryBackfillTaskStore
from kline.jobs import HeavyTaskCoordinator, JobStore


def bars(count: int, *, end: date = date(2026, 7, 7)) -> pd.DataFrame:
    dates = [end - timedelta(days=offset) for offset in range(count - 1, -1, -1)]
    return pd.DataFrame(
        {
            "date": dates,
            "open": [10.0] * count,
            "high": [11.0] * count,
            "low": [9.0] * count,
            "close": [10.5] * count,
            "volume": [100] * count,
            "amount": [1000.0] * count,
        }
    )


def factors() -> pd.DataFrame:
    return pd.DataFrame(
        [{"date": date(1900, 1, 1), "qfq_factor": 1.0, "hfq_factor": 1.0}]
    )


def test_scan_returns_only_supported_short_current_snapshots(tmp_path):
    pipeline = DatasetPipeline(tmp_path / "data")
    pipeline.initialize_catalog()
    pipeline.import_security("sh", "600000", bars(90), factors())
    pipeline.import_security("sz", "000001", bars(300), factors())
    pipeline.import_security("bj", "920001", bars(80), factors())

    candidates = HistoryBackfillService(pipeline, source=None, min_days=250).scan()

    assert [(item.exchange, item.code, item.before_count) for item in candidates] == [
        ("sh", "600000", 90)
    ]


def test_scan_skips_acknowledged_listing_with_unchanged_content_hash(tmp_path):
    pipeline = DatasetPipeline(tmp_path / "data")
    pipeline.initialize_catalog()
    pipeline.import_security("sh", "600000", bars(90), factors())
    manifest = pipeline.dataset_manifest_rows()[0]
    pipeline.record_quality_event(
        manifest["dataset_key"],
        "listing-history-short",
        "info",
        "confirmed new listing",
        content_hash=manifest["content_hash"],
    )

    candidates = HistoryBackfillService(pipeline, source=None, min_days=250).scan()

    assert candidates == []


class LongHistorySource:
    def __init__(self, raw: pd.DataFrame):
        self.raw = raw
        self.calls = []

    def fetch_long_history_bundle(self, exchange, code, start, end):
        self.calls.append((exchange, code, start, end))
        return self.raw.copy(), factors()


def short_candidate(pipeline: DatasetPipeline):
    pipeline.import_security("sh", "600000", bars(90), factors())
    return HistoryBackfillService(pipeline, source=None, min_days=250).scan()[0]


def test_backfill_replaces_short_snapshot_and_records_counts(tmp_path):
    pipeline = DatasetPipeline(tmp_path / "data")
    pipeline.initialize_catalog()
    candidate = short_candidate(pipeline)
    service = HistoryBackfillService(
        pipeline, LongHistorySource(bars(400)), min_days=250
    )

    result = service.backfill(candidate, as_of_date=date(2026, 7, 7))

    assert result.status == "completed"
    assert result.before_count == 90
    assert result.after_count == 400
    latest = pd.read_parquet(pipeline.latest_derived_path("sh", "600000"))
    assert len(latest) == 400
    event = pipeline.quality_events()[0]
    assert event["event_type"] == "history-backfilled"
    assert "90 -> 400" in event["message"]


def test_backfill_acknowledges_fresh_listing_history(tmp_path):
    pipeline = DatasetPipeline(tmp_path / "data")
    pipeline.initialize_catalog()
    candidate = short_candidate(pipeline)
    service = HistoryBackfillService(
        pipeline, LongHistorySource(bars(120)), min_days=250, freshness_days=10
    )

    result = service.backfill(candidate, as_of_date=date(2026, 7, 7))

    assert result.status == "listing_history_short"
    assert result.after_count == 120
    manifest = pipeline.dataset_manifest_rows()[0]
    event = pipeline.quality_events()[0]
    assert event["event_type"] == "listing-history-short"
    assert event["content_hash"] == manifest["content_hash"]


def test_backfill_rejects_stale_short_response_and_preserves_snapshot(tmp_path):
    pipeline = DatasetPipeline(tmp_path / "data")
    pipeline.initialize_catalog()
    candidate = short_candidate(pipeline)
    old_path = pipeline.latest_derived_path("sh", "600000")
    stale = bars(120, end=date(2026, 6, 1))
    service = HistoryBackfillService(
        pipeline, LongHistorySource(stale), min_days=250, freshness_days=10
    )

    with pytest.raises(BackfillCoverageError) as error:
        service.backfill(candidate, as_of_date=date(2026, 7, 7))

    assert error.value.code == "HISTORY_COVERAGE_INCOMPLETE"
    assert pipeline.latest_derived_path("sh", "600000") == old_path
    assert pipeline.quality_events()[0]["event_type"] == "history-backfill-failed"


def test_task_isolates_security_failure_and_keeps_processing(tmp_path):
    candidates = [
        BackfillCandidate("sh", "600000", Path("a"), "s1", "h1", 90),
        BackfillCandidate("sz", "000001", Path("b"), "s2", "h2", 100),
    ]

    class Service:
        def backfill(self, candidate, *, as_of_date):
            if candidate.code == "600000":
                raise BackfillCoverageError("HISTORY_COVERAGE_INCOMPLETE", "stale")
            return BackfillResult("completed", 100, 500, "s3")

    store = JobStore(tmp_path / "jobs.duckdb")
    coordinator = HeavyTaskCoordinator(store)
    tasks = HistoryBackfillTaskStore(coordinator, store, threading.Lock())
    task_id = tasks.submit(Service(), candidates, date(2026, 7, 7))

    coordinator.shutdown()
    result = store.get(task_id).result
    store.close()

    assert result["done"] == result["total"] == 2
    assert result["completed"] == 1
    assert result["listingHistoryShort"] == 0
    assert result["errors"] == [
        {
            "security": "sh600000",
            "stage": "history-fetch",
            "code": "HISTORY_COVERAGE_INCOMPLETE",
            "message": "stale",
        }
    ]


def test_task_times_out_stuck_history_fetch_and_continues(tmp_path):
    candidates = [
        BackfillCandidate("sh", "600000", Path("a"), "s1", "h1", 90),
        BackfillCandidate("sz", "000001", Path("b"), "s2", "h2", 100),
    ]
    failures = []

    class Service:
        def fetch_history_bundle(self, candidate, *, as_of_date):
            if candidate.code == "600000":
                time.sleep(1)
            return bars(500), factors()

        def apply_history_bundle(self, candidate, raw, factors, *, as_of_date):
            return BackfillResult("completed", candidate.before_count, len(raw), "s3")

        def record_failure(self, candidate, exc):
            failures.append((candidate.exchange, candidate.code, exc.code, str(exc)))

    store = JobStore(tmp_path / "jobs.duckdb")
    coordinator = HeavyTaskCoordinator(store)
    tasks = HistoryBackfillTaskStore(coordinator, store, threading.Lock())
    task_id = tasks.submit(
        Service(), candidates, date(2026, 7, 7), timeout_seconds=0.05
    )

    coordinator.shutdown()
    result = store.get(task_id).result
    store.close()

    assert result["done"] == result["total"] == 2
    assert result["completed"] == 1
    assert result["errors"] == [
        {
            "security": "sh600000",
            "stage": "history-fetch",
            "code": "HISTORY_FETCH_TIMEOUT",
            "message": "history fetch timed out after 0.05s",
        }
    ]
    assert failures == [
        (
            "sh",
            "600000",
            "HISTORY_FETCH_TIMEOUT",
            "history fetch timed out after 0.05s",
        )
    ]

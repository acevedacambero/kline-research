from datetime import date
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import time

import pandas as pd
import pytest

from kline.data.pipeline import DatasetPipeline


def test_dataset_pipeline_serializes_catalog_connections(tmp_path):
    pipeline = DatasetPipeline(tmp_path / "output")
    pipeline.initialize_catalog()
    counter_lock = threading.Lock()
    active = 0
    max_active = 0

    def hold_connection() -> None:
        nonlocal active, max_active
        with pipeline.connection():
            with counter_lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.05)
            with counter_lock:
                active -= 1

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(hold_connection) for _ in range(2)]
        for future in futures:
            future.result()

    assert max_active == 1


def test_dataset_pipeline_writes_parquet_and_catalog(tmp_path):
    output = tmp_path / "output"
    pipeline = DatasetPipeline(output)
    report = pipeline.initialize_catalog()
    assert Path(report.catalog_path).exists()
    assert report.status == "ready"


def test_pipeline_resolves_legacy_windows_manifest_paths(tmp_path):
    output = tmp_path / "data"
    pipeline = DatasetPipeline(output)
    pipeline.initialize_catalog()
    expected = output / "data-foundation-v1" / "snapshots" / "s1" / "derived" / "sh" / "600000.parquet"
    expected.parent.mkdir(parents=True)
    expected.write_bytes(b"placeholder")
    with pipeline.connection() as connection:
        connection.execute(
            """insert into dataset_manifest(
                dataset_key, content_hash, dataset_version, derived_path, snapshot_version
            ) values ('stock:sh:600000', 'hash', 'v1', ?, 's1')""",
            [r"data\data-foundation-v1\snapshots\s1\derived\sh\600000.parquet"],
        )

    assert pipeline.latest_derived_path("sh", "600000") == expected
    assert pipeline.cached_securities()[0]["derived_path"] == str(expected)
    assert pipeline.dataset_manifest_rows()[0]["derived_path"] == str(expected)


def test_pipeline_imports_raw_and_factor_facts_then_builds_derived_views(tmp_path):
    raw = pd.DataFrame([{"date": date(2024, 1, 2), "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 100, "amount": 1000.0}])
    factors = pd.DataFrame([{"date": date(1900, 1, 1), "qfq_factor": 2.0, "hfq_factor": 3.0, "factor_source": "sina"}])
    pipeline = DatasetPipeline(tmp_path / "output")
    pipeline.initialize_catalog()
    first = pipeline.import_security("sh", "600000", raw, factors)
    second = pipeline.import_security("sh", "600000", raw, factors)
    assert first.status == "imported"
    assert Path(first.parquet_path).exists()
    derived = pd.read_parquet(first.normalized_path)
    assert derived.iloc[0]["close"] == 10.5
    assert derived.iloc[0]["close_qfq"] == 5.25
    assert first.snapshot_version.startswith("snapshot-")
    assert pipeline.latest_derived_path("sh", "600000") == Path(first.normalized_path)
    assert second.status == "unchanged"


def test_factor_coverage_failure_is_recorded_as_quality_event(tmp_path):
    raw = pd.DataFrame([{"date": date(2024, 1, 1), "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 1, "amount": 1.0}])
    factors = pd.DataFrame([{"date": date(2024, 2, 1), "qfq_factor": 1.0, "hfq_factor": 1.0}])
    pipeline = DatasetPipeline(tmp_path / "output")
    pipeline.initialize_catalog()
    with pytest.raises(ValueError, match="do not cover"):
        pipeline.import_security("sh", "600000", raw, factors)
    events = pipeline.quality_events()
    assert events[0]["event_type"] == "factor-coverage-error"


def test_approximate_factor_source_is_recorded_as_quality_event(tmp_path):
    raw = pd.DataFrame([{"date": date(2024, 1, 2), "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 100, "amount": 1000.0}])
    factors = pd.DataFrame([{"date": date(1900, 1, 1), "qfq_factor": 1.0, "hfq_factor": 1.0, "factor_source": "stock_zh_a_daily_approx"}])
    pipeline = DatasetPipeline(tmp_path / "output")
    pipeline.initialize_catalog()

    report = pipeline.import_security("sh", "689009", raw, factors)

    events = pipeline.quality_events()
    assert events[0]["event_type"] == "factor-approximation"
    assert events[0]["content_hash"] == pipeline.dataset_manifest_rows()[0]["content_hash"]
    assert report.status == "imported"


def test_full_import_cannot_replace_complete_history_with_short_window(tmp_path):
    def bars(days: list[int], close_offset: float = 0.0) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "date": date(2024, 1, day),
                    "open": 10.0 + close_offset,
                    "high": 11.0 + close_offset,
                    "low": 9.0 + close_offset,
                    "close": 10.5 + close_offset,
                    "volume": 100,
                    "amount": 1000.0,
                }
                for day in days
            ]
        )

    factors = pd.DataFrame(
        [{"date": date(1900, 1, 1), "qfq_factor": 1.0, "hfq_factor": 1.0}]
    )
    pipeline = DatasetPipeline(tmp_path / "output")
    pipeline.initialize_catalog()
    pipeline.import_security("sh", "600000", bars([1, 2, 3, 4, 5]), factors)

    pipeline.import_security("sh", "600000", bars([4, 5], close_offset=1.0), factors)

    latest = pd.read_parquet(pipeline.latest_derived_path("sh", "600000"))
    assert list(pd.to_datetime(latest["date"]).dt.day) == [1, 2, 3, 4, 5]
    assert latest.loc[pd.to_datetime(latest["date"]).dt.day == 5, "close"].iloc[0] == 11.5
    event = pipeline.quality_events()[0]
    assert event["event_type"] == "history-shrink-prevented"
    assert "5 to 2" in event["message"]

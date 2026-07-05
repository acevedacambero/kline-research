from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from kline.data.pipeline import DatasetPipeline


def test_dataset_pipeline_writes_parquet_and_catalog(tmp_path):
    output = tmp_path / "output"
    pipeline = DatasetPipeline(output)
    report = pipeline.initialize_catalog()
    assert Path(report.catalog_path).exists()
    assert report.status == "ready"


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

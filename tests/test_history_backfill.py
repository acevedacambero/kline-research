from datetime import date, timedelta

import pandas as pd

from kline.data.history_backfill import HistoryBackfillService
from kline.data.pipeline import DatasetPipeline


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

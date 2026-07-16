from datetime import date, timedelta

import pandas as pd

from kline.data.coverage import MarketCoverageService
from kline.data.pipeline import DatasetPipeline


def _bars(start: date, count: int):
    return pd.DataFrame(
        [
            {
                "date": start + timedelta(days=index),
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "volume": 100,
                "amount": 1000.0,
            }
            for index in range(count)
        ]
    )


def _factors():
    return pd.DataFrame(
        [{"date": date(1900, 1, 1), "qfq_factor": 1.0, "hfq_factor": 1.0}]
    )


def test_coverage_report_classifies_ready_short_missing_and_approximate(tmp_path):
    pipeline = DatasetPipeline(tmp_path / "data")
    pipeline.initialize_catalog()
    pipeline.import_security("sh", "600000", _bars(date(2024, 1, 1), 12), _factors())
    pipeline.import_security("sz", "000001", _bars(date(2024, 1, 8), 5), _factors())
    pipeline.import_security("sh", "600001", _bars(date(2024, 1, 1), 12), _factors())
    service = MarketCoverageService(
        pipeline,
        tmp_path / "coverage.json",
        min_history_rows=10,
        freshness_days=10,
        gap_days=30,
    )

    report = service.build(
        [
            {"exchange": "sh", "code": "600000", "name": "浦发银行"},
            {"exchange": "sz", "code": "000001", "name": "平安银行"},
            {"exchange": "sh", "code": "600001", "name": "近似因子"},
            {"exchange": "sz", "code": "000002", "name": "缺失"},
        ],
        approximate_securities={"sh600001"},
    )

    statuses = {item["security"]: item["status"] for item in report["securities"]}
    assert statuses == {
        "sh600000": "ready",
        "sz000001": "short_history",
        "sh600001": "approximate_factor",
        "sz000002": "missing",
    }
    assert report["readyCount"] == 1
    assert report["coverageRate"] == 0.25
    assert service.load()["version"] == "market-coverage-v2-suspension-aware"
    assert {item["security"] for item in service.repair_queue()} == {
        "sz000001",
        "sh600001",
        "sz000002",
    }


def test_incremental_import_merges_dates_and_replaces_overlap(tmp_path):
    pipeline = DatasetPipeline(tmp_path / "data")
    pipeline.initialize_catalog()
    initial = _bars(date(2024, 1, 1), 3)
    pipeline.import_security("sh", "600000", initial, _factors())
    update = _bars(date(2024, 1, 3), 2)
    update.loc[0, "close"] = 99.0

    pipeline.import_incremental_security("sh", "600000", update, _factors())

    frame = pd.read_parquet(pipeline.latest_derived_path("sh", "600000"))
    assert len(frame) == 4
    assert frame.loc[pd.to_datetime(frame["date"]).dt.date == date(2024, 1, 3), "close"].item() == 99
    assert pipeline.latest_data_date("sh", "600000") == date(2024, 1, 4)


def test_long_calendar_interval_is_advisory_not_repairable_gap(tmp_path):
    pipeline = DatasetPipeline(tmp_path / "data")
    pipeline.initialize_catalog()
    bars = _bars(date(2024, 1, 1), 10)
    bars.loc[9, "date"] = date(2024, 2, 20)
    pipeline.import_security("sh", "600000", bars, _factors())
    service = MarketCoverageService(
        pipeline,
        tmp_path / "coverage.json",
        min_history_rows=10,
        freshness_days=10,
        gap_days=10,
    )

    report = service.build(
        [{"exchange": "sh", "code": "600000", "name": "浦发银行"}]
    )

    item = report["securities"][0]
    assert item["status"] == "ready"
    assert item["calendarGapCount"] == 1
    assert item["repairable"] is False
    assert "停牌或节假日" in item["reason"]
    assert service.repair_queue() == []

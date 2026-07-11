from datetime import date, timedelta

from pathlib import Path

from kline.p1.batch import BatchLabelBuilder, LabelDatasetStore, filter_mature_samples


def make_bars(count: int, start: float = 10.0):
    rows = []
    for index in range(count):
        price = start * (1 + index * 0.0005)
        rows.append({
            "date": date(2020, 1, 1) + timedelta(days=index),
            "open": price, "high": price * 1.01, "low": price * 0.99, "close": price,
            "open_qfq": price, "high_qfq": price * 1.01, "low_qfq": price * 0.99, "close_qfq": price,
            "open_total_return": price, "high_total_return": price * 1.01,
            "low_total_return": price * 0.99, "close_total_return": price,
            "volume": 1000, "amount": 10000,
            "factor_version": "factor-test",
        })
    return rows


def test_batch_builder_emits_versioned_mature_multi_horizon_labels():
    bars = make_bars(340)
    builder = BatchLabelBuilder(sample_step=5, horizons=(5, 10, 20, 60))
    rows = builder.build("sh", "600000", bars, make_bars(340, 100.0), "snapshot-test")
    assert rows
    first = rows[0]
    assert first["signal_index"] == 250
    assert first["snapshot_version"] == "snapshot-test"
    assert first["factor_version"] == "factor-test"
    assert first["label_definition_version"] == "daily-v2-exit-delay"
    assert first["p20_status"] == "ok"
    assert "p60_executable_return" in first
    assert first["p20_exit_status"] == "executable"
    assert first["p20_exit_delay"] == 0
    assert first["p20_delayed_executable_return"] == first["p20_executable_return"]
    assert all(row["p60_exit_status"] != "insufficient-forward-data" for row in rows)
    assert first["label_maturity_date"] > first["signal_date"]


def test_walk_forward_filter_rejects_future_and_unmatured_samples():
    samples = [
        {"signal_date": date(2024, 1, 1), "label_maturity_date": date(2024, 2, 1)},
        {"signal_date": date(2024, 2, 1), "label_maturity_date": date(2024, 4, 1)},
        {"signal_date": date(2024, 5, 1), "label_maturity_date": date(2024, 6, 1)},
    ]
    filtered = filter_mature_samples(samples, date(2024, 3, 1))
    assert filtered == [samples[0]]


def test_label_store_writes_versioned_parquet(tmp_path):
    rows = [{"exchange": "sh", "code": "600000", "signal_date": date(2024, 1, 1), "snapshot_version": "snapshot-x"}]
    report = LabelDatasetStore(tmp_path).write("sh", "600000", rows)
    assert report.status == "written"
    assert Path(report.path).exists()
    assert "snapshot-x" in report.path

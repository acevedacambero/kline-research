from datetime import date, timedelta

import numpy as np
import pandas as pd

from kline.monitoring.drift import DRIFT_DEFINITION_VERSION, compute_feature_drift


def drift_rows(*, shifted: bool = False) -> pd.DataFrame:
    start = date(2024, 1, 1)
    rows = []
    for day in range(180):
        for exchange in ("sh", "sz"):
            cycle = (day % 20) / 20
            recent_shift = 2.0 if shifted and day >= 150 else 0.0
            rows.append(
                {
                    "exchange": exchange,
                    "date": start + timedelta(days=day),
                    "score": 40 + cycle * 20 + recent_shift * 10,
                    "bullish_alignment": day % 3 == 0,
                    "return_20": cycle / 10 + recent_shift,
                    "volume_ratio_5": 0.8 + cycle,
                    "volatility_20": 0.1 + cycle / 10,
                }
            )
    return pd.DataFrame(rows)


def test_feature_drift_reports_stable_repeated_distribution_and_exchange_segments():
    result = compute_feature_drift(drift_rows(), recent_days=40, reference_days=120)

    assert result["version"] == DRIFT_DEFINITION_VERSION
    assert result["status"] == "stable"
    assert result["referenceWindow"]["tradingDays"] == 120
    assert result["recentWindow"]["tradingDays"] == 40
    assert {segment["exchange"] for segment in result["segments"]} == {"sh", "sz"}
    assert all(metric["populationStabilityIndex"] < 0.1 for metric in result["metrics"])


def test_feature_drift_detects_recent_distribution_and_missingness_change():
    rows = drift_rows(shifted=True)
    rows.loc[rows["date"] >= date(2024, 5, 30), "volume_ratio_5"] = np.nan

    result = compute_feature_drift(rows, recent_days=30, reference_days=120)
    by_column = {metric["column"]: metric for metric in result["metrics"]}

    assert result["status"] == "drift"
    assert by_column["return_20"]["standardizedMeanShift"] >= 0.5
    assert by_column["return_20"]["status"] == "drift"
    assert by_column["volume_ratio_5"]["missingRateDelta"] >= 0.1
    assert by_column["volume_ratio_5"]["status"] == "drift"


def test_feature_drift_reports_missing_columns_and_short_history():
    missing = compute_feature_drift([{"exchange": "sh", "score": 1}])
    short = compute_feature_drift(
        [{"date": date(2024, 1, 1), "score": 1}], recent_days=10, reference_days=30
    )

    assert missing["status"] == "insufficient_data"
    assert missing["warnings"] == ["缺少日期或监控字段"]
    assert short["status"] == "insufficient_data"
    assert short["warnings"] == ["基准窗口或近期窗口样本不足"]

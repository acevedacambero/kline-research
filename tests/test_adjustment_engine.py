from datetime import date

import pandas as pd
import pytest

from kline.data.adjustment import DerivedAdjustmentEngine, merge_raw_segments


def test_derived_views_use_effective_factor_without_mutating_raw_prices():
    raw = pd.DataFrame([
        {"date": date(2024, 7, 17), "open": 8.80, "high": 9.10, "low": 8.70, "close": 9.04, "volume": 10, "amount": 100},
        {"date": date(2024, 7, 18), "open": 8.80, "high": 8.90, "low": 8.70, "close": 8.77, "volume": 11, "amount": 110},
    ])
    factors = pd.DataFrame([
        {"date": date(2023, 7, 21), "qfq_factor": 1.068258, "hfq_factor": 8.0},
        {"date": date(2024, 7, 18), "qfq_factor": 1.030325, "hfq_factor": 8.3},
    ])
    result = DerivedAdjustmentEngine().derive(raw, factors)
    assert result.loc[0, "close"] == 9.04
    assert result.loc[0, "close_qfq"] == pytest.approx(9.04 / 1.068258)
    assert result.loc[1, "close_qfq"] == pytest.approx(8.77 / 1.030325)
    assert result.loc[1, "close_hfq"] == pytest.approx(8.77 * 8.3)
    assert result.loc[1, "close_total_return"] == result.loc[1, "close_hfq"]


def test_cross_provider_merge_accepts_raw_and_rejects_adjusted_segments():
    raw = pd.DataFrame([{"date": date(2024, 1, 1), "close": 10.0}])
    merged = merge_raw_segments([("eastmoney", raw), ("sina", raw)])
    assert len(merged) == 1
    adjusted = raw.assign(close_qfq=9.0)
    with pytest.raises(ValueError, match="adjusted columns"):
        merge_raw_segments([("eastmoney", adjusted)])

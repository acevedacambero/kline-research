from datetime import date, timedelta

import pandas as pd
import pytest

from kline.features import compute_daily_features


def feature_bars(count: int = 260) -> pd.DataFrame:
    rows = []
    start = date(2024, 1, 1)
    for index in range(count):
        close = 10.0 + index
        rows.append(
            {
                "date": start + timedelta(days=index),
                "open": close - 0.2,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "open_qfq": close - 0.2,
                "high_qfq": close + 1.0,
                "low_qfq": close - 1.0,
                "close_qfq": close,
                "close_total_return": close * 2.0,
                "volume": 100.0 + index,
                "amount": 1000.0 + index,
                "factor_version": "factor-test",
            }
        )
    return pd.DataFrame(rows)


def test_trend_features_are_point_in_time_and_use_qfq_prices():
    bars = feature_bars(65)
    result = compute_daily_features(bars, exchange="sh", code="600000")

    row = result.iloc[-1]
    assert row["ma5"] == pytest.approx(sum(range(70, 75)) / 5)
    assert row["ma60"] == pytest.approx(sum(range(15, 75)) / 60)
    assert bool(row["bullish_alignment"]) is True
    assert row["close_to_ma5"] == pytest.approx(74 / 72 - 1)
    assert pd.isna(result.iloc[3]["ma5"])

    changed_future = pd.concat(
        [bars, feature_bars(1).assign(date=date(2030, 1, 1), close_qfq=9999.0)],
        ignore_index=True,
    )
    changed = compute_daily_features(changed_future, exchange="sh", code="600000")
    assert changed.loc[changed["date"] == bars.iloc[-1]["date"], "ma5"].iloc[0] == row["ma5"]


def test_position_and_momentum_use_qfq_and_total_return_respectively():
    result = compute_daily_features(feature_bars(), exchange="sh", code="600000")
    row = result.iloc[-1]

    assert row["range_position_20"] == pytest.approx((269 - 249) / (270 - 249))
    assert row["drawdown_from_high_20"] == pytest.approx(269 / 270 - 1)
    assert row["return_5"] == pytest.approx(269 / 264 - 1)
    assert row["return_120"] == pytest.approx(269 / 149 - 1)
    assert pd.isna(result.iloc[118]["range_position_120"])
    assert pd.isna(result.iloc[119]["return_120"])


def test_volume_price_features_have_explicit_complete_windows():
    result = compute_daily_features(feature_bars(), exchange="sh", code="600000")
    row = result.iloc[-1]

    assert row["volume_ratio_5"] == pytest.approx(359 / ((354 + 355 + 356 + 357 + 358) / 5))
    assert row["volume_percentile_20"] == pytest.approx(1.0)
    assert row["amplitude"] == pytest.approx(2 / 268)
    assert row["volatility_20"] > 0
    assert row["amount"] == 1259.0
    assert pd.isna(result.iloc[4]["volume_ratio_5"])


def test_trading_behavior_uses_raw_prices_and_rule_width():
    bars = feature_bars(30)
    previous_close = bars.loc[27, "close"]
    limit_price = previous_close * 1.10
    bars.loc[28, ["open", "high", "low", "close"]] = limit_price
    bars.loc[29, ["open", "high", "low", "close"]] = limit_price * 1.10
    bars.loc[28:29, ["open_qfq", "high_qfq", "low_qfq", "close_qfq"]] = 1.0

    result = compute_daily_features(bars, exchange="sh", code="600000")
    row = result.iloc[-1]

    assert row["limit_up_count_20"] == 2
    assert row["locked_limit_up_streak"] == 2
    assert bool(row["is_limit_up"]) is True


def test_long_calendar_gap_is_marked_without_treating_weekends_as_suspension():
    bars = feature_bars(3)
    bars.loc[1, "date"] = date(2024, 1, 5)
    bars.loc[2, "date"] = date(2024, 1, 20)

    result = compute_daily_features(bars, exchange="sh", code="600000")

    assert result.iloc[1]["suspension_gap_days"] == 0
    assert result.iloc[2]["suspension_gap_days"] == 14
    assert result.iloc[2]["gap_open"] == pytest.approx(bars.iloc[2]["open"] / bars.iloc[1]["close"] - 1)
    assert result.iloc[-1]["available_history"] == 3
    assert result.iloc[-1]["price_basis"] == "raw+qfq+total-return"

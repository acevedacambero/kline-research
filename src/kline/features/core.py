from __future__ import annotations

import math

import pandas as pd

from kline.p1.core import limit_rule


FEATURE_DEFINITION_VERSION = "daily-features-v1"
MA_WINDOWS = (5, 10, 20, 60)
POSITION_WINDOWS = (20, 60, 120, 250)
MOMENTUM_WINDOWS = (5, 10, 20, 60, 120)


def _rolling_percentile(values: pd.Series) -> float:
    return float(values.rank(method="average", pct=True).iloc[-1])


def _locked_limit_streak(flags: pd.Series) -> pd.Series:
    streak = 0
    values: list[int] = []
    for flag in flags.fillna(False):
        streak = streak + 1 if bool(flag) else 0
        values.append(streak)
    return pd.Series(values, index=flags.index, dtype="int64")


def compute_daily_features(
    bars: pd.DataFrame | list[dict],
    *,
    exchange: str,
    code: str,
    st_status: bool = False,
) -> pd.DataFrame:
    frame = pd.DataFrame(bars).copy()
    if frame.empty:
        return frame
    required = {
        "date", "open", "high", "low", "close", "open_qfq", "high_qfq",
        "low_qfq", "close_qfq", "close_total_return", "volume",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"feature input missing columns: {', '.join(missing)}")

    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    frame = frame.sort_values("date", kind="stable").reset_index(drop=True)
    result = pd.DataFrame(
        {
            "date": frame["date"],
            "exchange": exchange,
            "code": code,
            "available_history": pd.Series(range(1, len(frame) + 1), dtype="int64"),
            "amount": pd.to_numeric(
                frame["amount"] if "amount" in frame else pd.Series(float("nan"), index=frame.index),
                errors="coerce",
            ),
        }
    )

    close_qfq = pd.to_numeric(frame["close_qfq"], errors="coerce")
    for window in MA_WINDOWS:
        average = close_qfq.rolling(window, min_periods=window).mean()
        result[f"ma{window}"] = average
        result[f"ma{window}_slope"] = average / average.shift(5) - 1
        result[f"close_to_ma{window}"] = close_qfq / average - 1
    result["bullish_alignment"] = (
        (result["ma5"] > result["ma10"])
        & (result["ma10"] > result["ma20"])
        & (result["ma20"] > result["ma60"])
    )
    result["bearish_alignment"] = (
        (result["ma5"] < result["ma10"])
        & (result["ma10"] < result["ma20"])
        & (result["ma20"] < result["ma60"])
    )

    high_qfq = pd.to_numeric(frame["high_qfq"], errors="coerce")
    low_qfq = pd.to_numeric(frame["low_qfq"], errors="coerce")
    for window in POSITION_WINDOWS:
        rolling_high = high_qfq.rolling(window, min_periods=window).max()
        rolling_low = low_qfq.rolling(window, min_periods=window).min()
        width = rolling_high - rolling_low
        result[f"range_position_{window}"] = (close_qfq - rolling_low) / width.where(width != 0)
        result[f"drawdown_from_high_{window}"] = close_qfq / rolling_high - 1

    total_return = pd.to_numeric(frame["close_total_return"], errors="coerce")
    daily_return = total_return.pct_change(fill_method=None)
    for window in MOMENTUM_WINDOWS:
        result[f"return_{window}"] = total_return / total_return.shift(window) - 1

    volume = pd.to_numeric(frame["volume"], errors="coerce")
    result["volume_ratio_5"] = volume / volume.shift(1).rolling(5, min_periods=5).mean()
    result["volume_percentile_20"] = volume.rolling(20, min_periods=20).apply(
        _rolling_percentile, raw=False
    )
    result["volatility_20"] = daily_return.rolling(20, min_periods=20).std(ddof=0)
    result["amplitude"] = (high_qfq - low_qfq) / close_qfq.shift(1)

    raw_open = pd.to_numeric(frame["open"], errors="coerce")
    raw_high = pd.to_numeric(frame["high"], errors="coerce")
    raw_low = pd.to_numeric(frame["low"], errors="coerce")
    raw_close = pd.to_numeric(frame["close"], errors="coerce")
    previous_close = raw_close.shift(1)
    result["gap_open"] = raw_open / previous_close - 1
    date_gap = pd.to_datetime(frame["date"]).diff().dt.days
    result["suspension_gap_days"] = (date_gap - 1).where(date_gap > 10, 0).fillna(0).astype(int)

    is_limit_up: list[bool] = []
    is_locked_limit_up: list[bool] = []
    approximate: list[bool] = []
    rule_reasons: list[str | None] = []
    for index, row in frame.iterrows():
        rule = limit_rule(code, row["date"], exchange, st_status)
        approximate.append(rule.is_approx)
        rule_reasons.append(rule.reason)
        if index == 0 or math.isnan(previous_close.iloc[index]):
            is_limit_up.append(False)
            is_locked_limit_up.append(False)
            continue
        target = previous_close.iloc[index] * (1 + rule.limit_width)
        tolerance = max(0.011, target * 0.0015)
        limit_hit = raw_close.iloc[index] >= target - tolerance
        locked = limit_hit and max(
            abs(raw_open.iloc[index] - raw_close.iloc[index]),
            abs(raw_high.iloc[index] - raw_close.iloc[index]),
            abs(raw_low.iloc[index] - raw_close.iloc[index]),
        ) <= tolerance
        is_limit_up.append(bool(limit_hit))
        is_locked_limit_up.append(bool(locked))

    result["is_limit_up"] = is_limit_up
    result["limit_up_count_20"] = pd.Series(is_limit_up, dtype="int64").rolling(
        20, min_periods=20
    ).sum()
    result["locked_limit_up_streak"] = _locked_limit_streak(pd.Series(is_locked_limit_up))
    result["is_approx"] = approximate
    result["rule_reason"] = rule_reasons
    result["reasons"] = [[] for _ in range(len(result))]
    result["price_basis"] = "raw+qfq+total-return"
    result["feature_definition_version"] = FEATURE_DEFINITION_VERSION
    result["limit_rule_version"] = "cn-equity-v1"
    if "factor_version" in frame:
        result["factor_version"] = frame["factor_version"].astype(str)
    return result

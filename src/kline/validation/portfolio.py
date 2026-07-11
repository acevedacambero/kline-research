from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd


PORTFOLIO_VALIDATION_VERSION = "p8-top-score-portfolio-v1"


def validate_top_score_portfolio(scores: pd.DataFrame | list[dict], labels: pd.DataFrame | list[dict], *, label_column: str = "p20_executable_return", top_fraction: float = 0.1, as_of_date: date | None = None) -> dict[str, Any]:
    base = {"version": PORTFOLIO_VALIDATION_VERSION, "labelColumn": label_column, "topFraction": top_fraction, "sampleCount": 0, "tradingDayCount": 0, "selectedCount": 0, "averageReturn": None, "benchmarkReturn": None, "excessReturn": None, "winRate": None, "warnings": []}
    sf, lf = pd.DataFrame(scores).copy(), pd.DataFrame(labels).copy()
    required = {"exchange", "code", "date", "score"} | {"signal_date", label_column}
    if not required.issubset(set(sf.columns) | set(lf.columns)) or not {"exchange", "code", "date", "score"}.issubset(sf.columns) or not {"exchange", "code", "signal_date", label_column}.issubset(lf.columns):
        base["warnings"] = ["缺少评分或标签字段"]
        return base
    sf["date"] = pd.to_datetime(sf["date"]).dt.date
    lf["signal_date"] = pd.to_datetime(lf["signal_date"]).dt.date
    merged = sf.merge(lf, left_on=["exchange", "code", "date"], right_on=["exchange", "code", "signal_date"])
    if "usable" in merged:
        merged = merged.loc[merged["usable"].fillna(False).astype(bool)]
    if as_of_date is not None:
        merged = merged.loc[merged["date"] <= as_of_date]
    merged["score"] = pd.to_numeric(merged["score"], errors="coerce")
    merged[label_column] = pd.to_numeric(merged[label_column], errors="coerce")
    merged = merged.dropna(subset=["score", label_column])
    if merged.empty:
        return {**base, "warnings": ["没有可用成熟样本"]}
    fraction = max(0.01, min(1.0, float(top_fraction)))
    selected = merged.groupby("date", group_keys=False).apply(lambda frame: frame.nlargest(max(1, int(len(frame) * fraction)), "score"), include_groups=False)
    selected_returns = selected[label_column]
    benchmark = merged[label_column]
    warnings = ["未计交易成本、滑点和卖出顺延", "前瞻收益窗口存在重叠，暂不计算组合最大回撤"]
    if len(selected) < 20:
        warnings.append("入选样本少于 20，仅供探索")
    return {**base, "sampleCount": int(len(merged)), "tradingDayCount": int(merged["date"].nunique()), "selectedCount": int(len(selected)), "averageReturn": float(selected_returns.mean()), "benchmarkReturn": float(benchmark.mean()), "excessReturn": float(selected_returns.mean() - benchmark.mean()), "winRate": float((selected_returns > 0).mean()), "maxDrawdown": None, "warnings": warnings}

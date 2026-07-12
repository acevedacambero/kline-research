from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd


PORTFOLIO_VALIDATION_VERSION = "p8-top-score-portfolio-v3-equity"


def validate_top_score_portfolio(scores: pd.DataFrame | list[dict], labels: pd.DataFrame | list[dict], *, label_column: str = "p20_executable_return", top_fraction: float = 0.1, as_of_date: date | None = None, non_overlapping: bool = False, transaction_cost_bps: float = 0, slippage_bps: float = 0) -> dict[str, Any]:
    base = {"version": PORTFOLIO_VALIDATION_VERSION, "labelColumn": label_column, "topFraction": top_fraction, "sampleCount": 0, "tradingDayCount": 0, "selectedCount": 0, "averageReturn": None, "benchmarkReturn": None, "excessReturn": None, "winRate": None, "annualizedReturn": None, "annualizedVolatility": None, "sharpeRatio": None, "calmarRatio": None, "equityCurve": [], "warnings": []}
    sf, lf = pd.DataFrame(scores).copy(), pd.DataFrame(labels).copy()
    required = {"exchange", "code", "date", "score"} | {"signal_date", label_column}
    if not required.issubset(set(sf.columns) | set(lf.columns)) or not {"exchange", "code", "date", "score"}.issubset(sf.columns) or not {"exchange", "code", "signal_date", label_column}.issubset(lf.columns):
        base["warnings"] = ["缺少评分或标签字段"]
        return base
    sf["date"] = pd.to_datetime(sf["date"]).dt.date
    available_as_of = sf["date"].max()
    lf["signal_date"] = pd.to_datetime(lf["signal_date"]).dt.date
    merged = sf.merge(lf, left_on=["exchange", "code", "date"], right_on=["exchange", "code", "signal_date"])
    if "usable" in merged:
        merged = merged.loc[merged["usable"].fillna(False).astype(bool)]
    effective_as_of = as_of_date or available_as_of
    merged = merged.loc[merged["date"] <= effective_as_of]
    if "label_maturity_date" in merged:
        maturity = pd.to_datetime(merged["label_maturity_date"], errors="coerce").dt.date
        merged = merged.loc[maturity <= effective_as_of]
    merged["score"] = pd.to_numeric(merged["score"], errors="coerce")
    merged[label_column] = pd.to_numeric(merged[label_column], errors="coerce")
    merged = merged.dropna(subset=["score", label_column])
    if merged.empty:
        return {**base, "warnings": ["没有可用成熟样本"]}
    fraction = max(0.01, min(1.0, float(top_fraction)))
    horizon = next((value for value in (5, 10, 20, 60) if f"p{value}_" in label_column), 20)
    if non_overlapping:
        dates = sorted(merged["date"].unique())
        selected_dates = set(dates[::horizon])
        merged = merged.loc[merged["date"].isin(selected_dates)]
    selected = pd.concat([
        frame.nlargest(max(1, int(len(frame) * fraction)), "score")
        for _trading_date, frame in merged.groupby("date", sort=True)
    ], ignore_index=True)
    selected_returns = selected[label_column]
    total_cost_rate = (max(0.0, transaction_cost_bps) + max(0.0, slippage_bps)) / 10_000
    net_returns = selected_returns - total_cost_rate
    benchmark = merged[label_column]
    warnings = []
    if "delayed_executable_return" not in label_column:
        warnings.append("卖出使用计划持有期收盘，未模拟不可卖顺延")
    max_drawdown = None
    annualized_return = None
    annualized_volatility = None
    sharpe_ratio = None
    calmar_ratio = None
    equity_curve = []
    if non_overlapping:
        period_returns = net_returns.groupby(selected["date"]).mean().sort_index()
        curve = (1 + period_returns).cumprod()
        max_drawdown = float((curve / curve.cummax() - 1).min()) if not curve.empty else None
        periods_per_year = 252 / horizon
        if not curve.empty and bool((1 + period_returns > 0).all()):
            annualized_return = float(curve.iloc[-1] ** (periods_per_year / len(curve)) - 1)
        if len(period_returns) > 1:
            period_std = float(period_returns.std(ddof=1))
            annualized_volatility = float(period_std * np.sqrt(periods_per_year))
            if period_std > 0:
                sharpe_ratio = float(
                    period_returns.mean() / period_std * np.sqrt(periods_per_year)
                )
        if annualized_return is not None and max_drawdown is not None and max_drawdown < 0:
            calmar_ratio = float(annualized_return / abs(max_drawdown))
        equity_curve = [
            {"date": item.isoformat(), "value": float(value)}
            for item, value in curve.items()
        ]
    else:
        warnings.append("前瞻收益窗口存在重叠，暂不计算组合最大回撤")
    if len(selected) < 20:
        warnings.append("入选样本少于 20，仅供探索")
    return {**base, "sampleCount": int(len(merged)), "tradingDayCount": int(merged["date"].nunique()), "selectedCount": int(len(selected)), "averageReturn": float(selected_returns.mean()), "netAverageReturn": float(net_returns.mean()), "benchmarkReturn": float(benchmark.mean()), "excessReturn": float(selected_returns.mean() - benchmark.mean()), "netExcessReturn": float(net_returns.mean() - benchmark.mean()), "winRate": float((net_returns > 0).mean()), "maxDrawdown": max_drawdown, "annualizedReturn": annualized_return, "annualizedVolatility": annualized_volatility, "sharpeRatio": sharpe_ratio, "calmarRatio": calmar_ratio, "equityCurve": equity_curve, "nonOverlapping": non_overlapping, "transactionCostBps": transaction_cost_bps, "slippageBps": slippage_bps, "totalCostRate": total_cost_rate, "warnings": warnings}

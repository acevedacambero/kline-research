from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable


@dataclass(frozen=True)
class LimitRuleResult:
    limit_width: float | None
    executable_threshold: float | None
    no_limit: bool
    rule_version: str = "cn-equity-v1"
    is_approx: bool = False
    reason: str = ""


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    status: str
    reasons: list[str]


@dataclass(frozen=True)
class EntryResult:
    executable: bool
    status: str
    entry_index: int | None = None
    entry_date: date | str | None = None
    entry_price: float | None = None
    entry_delay: int | None = None
    entry_reason: str = ""


@dataclass(frozen=True)
class ForwardLabel:
    horizon: int
    theoretical_return: float | None
    executable_return: float | None
    excess_theoretical_return: float | None
    excess_executable_return: float | None
    status: str


@dataclass(frozen=True)
class PathResult:
    success: bool
    hit_date: date | str | None
    fail_date: date | str | None
    status: str
    reason: str


@dataclass(frozen=True)
class DrawdownResult:
    max_drawdown: float
    hit_risk: bool
    hit_date: date | str | None
    peak_date: date | str | None
    status: str


@dataclass(frozen=True)
class IndependentPeriodsResult:
    independent_n: int
    clusters: list[dict[str, Any]]


def limit_rule(
    code: str,
    trading_date: date,
    exchange: str,
    st_status: bool = False,
    *,
    no_limit: bool = False,
) -> LimitRuleResult:
    if no_limit:
        return LimitRuleResult(None, None, True, reason="no-limit trading window")
    if st_status:
        return LimitRuleResult(0.05, 0.04, False, is_approx=True, reason="approximated ST")
    if exchange.lower() == "bj":
        width = 0.30
    elif code.startswith(("300", "301", "688", "689")):
        width = 0.20
    else:
        width = 0.10
    threshold = {0.10: 0.097, 0.20: 0.194, 0.30: 0.291}[width]
    return LimitRuleResult(width, threshold, False, reason="board/date rule")


def _valid_ohlc(row: dict[str, Any]) -> bool:
    try:
        suffix = "" if "open" in row else "_qfq"
        o, h, low, c = (
            float(row[f"{key}{suffix}"]) for key in ("open", "high", "low", "close")
        )
        return min(o, h, low, c) > 0 and h >= max(o, low, c) and low <= min(o, h, c)
    except (KeyError, TypeError, ValueError):
        return False


def sample_eligibility(
    stock_series: list[dict[str, Any]],
    signal_index: int,
    *,
    rights_status: str = "ok",
    no_limit: bool = False,
) -> EligibilityResult:
    reasons: list[str] = []
    if signal_index >= len(stock_series) or not _valid_ohlc(stock_series[signal_index]):
        reasons.append("invalid-ohlc")
    if rights_status != "ok":
        reasons.append("rights-warn")
    if signal_index < 250:
        reasons.append("insufficient-history")
    if no_limit:
        reasons.append("noLimit-excluded")
    status = reasons[0] if reasons else "eligible"
    return EligibilityResult(not reasons, status, reasons)


def resolve_executable_entry(
    stock_series: list[dict[str, Any]],
    signal_index: int,
    *,
    code: str,
    exchange: str,
    st_status: bool = False,
    max_delay: int = 3,
    gap_days: int = 10,
    no_limit_indices: set[int] | None = None,
) -> EntryResult:
    no_limit_indices = no_limit_indices or set()
    for delay in range(1, max_delay + 1):
        idx = signal_index + delay
        if idx >= len(stock_series):
            return EntryResult(False, "insufficient-forward-data")
        previous = stock_series[idx - 1]
        current = stock_series[idx]
        if idx in no_limit_indices:
            return EntryResult(False, "noLimit-excluded", entry_reason="entry window has no price limit")
        previous_date, current_date = previous["date"], current["date"]
        if isinstance(previous_date, date) and isinstance(current_date, date):
            if (current_date - previous_date).days > gap_days:
                return EntryResult(False, "suspended-abandoned")
        rule = limit_rule(code, current_date, exchange, st_status)
        if rule.no_limit:
            return EntryResult(False, "noLimit-excluded")
        price_suffix = "" if "open" in current and "close" in previous else "_qfq"
        gain = float(current[f"open{price_suffix}"]) / float(previous[f"close{price_suffix}"]) - 1
        if gain < float(rule.executable_threshold):
            return EntryResult(
                True,
                "executable" if delay == 1 else "delayed",
                idx,
                current_date,
                float(current[f"open{price_suffix}"]),
                delay,
                "opening gain below executable threshold",
            )
    return EntryResult(False, "abandoned", entry_reason="entry blocked through T+3")


def _date_index(series: list[dict[str, Any]]) -> dict[Any, int]:
    return {row["date"]: idx for idx, row in enumerate(series)}


def compute_forward_labels(
    stock_series: list[dict[str, Any]],
    benchmark_series: list[dict[str, Any]],
    signal_index: int,
    entry_index: int,
    horizons: Iterable[int] = (5, 10, 20, 60),
    benchmark_date_index: dict[Any, int] | None = None,
) -> dict[int, ForwardLabel]:
    benchmark_dates = benchmark_date_index or _date_index(benchmark_series)
    output: dict[int, ForwardLabel] = {}
    stock_suffix = "_total_return" if "close_total_return" in stock_series[0] else "_qfq"
    benchmark_suffix = (
        "_total_return"
        if benchmark_series and "close_total_return" in benchmark_series[0]
        else "_qfq"
    )
    for horizon in horizons:
        close_end = signal_index + horizon
        exec_end = entry_index + horizon
        if close_end >= len(stock_series) or exec_end >= len(stock_series):
            output[horizon] = ForwardLabel(horizon, None, None, None, None, "insufficient-forward-data")
            continue
        theoretical = (
            stock_series[close_end][f"close{stock_suffix}"]
            / stock_series[signal_index][f"close{stock_suffix}"]
            - 1
        )
        executable = (
            stock_series[exec_end][f"close{stock_suffix}"]
            / stock_series[entry_index][f"open{stock_suffix}"]
            - 1
        )
        entry_date = stock_series[entry_index]["date"]
        exec_end_date = stock_series[exec_end]["date"]
        signal_date = stock_series[signal_index]["date"]
        close_end_date = stock_series[close_end]["date"]
        if not all(d in benchmark_dates for d in (entry_date, exec_end_date, signal_date, close_end_date)):
            output[horizon] = ForwardLabel(horizon, theoretical, executable, None, None, "benchmark-missing")
            continue
        b_theoretical = (
            benchmark_series[benchmark_dates[close_end_date]][f"close{benchmark_suffix}"]
            / benchmark_series[benchmark_dates[signal_date]][f"close{benchmark_suffix}"]
            - 1
        )
        b_executable = (
            benchmark_series[benchmark_dates[exec_end_date]][f"close{benchmark_suffix}"]
            / benchmark_series[benchmark_dates[entry_date]][f"open{benchmark_suffix}"]
            - 1
        )
        output[horizon] = ForwardLabel(
            horizon,
            theoretical,
            executable,
            (1 + theoretical) / (1 + b_theoretical) - 1,
            (1 + executable) / (1 + b_executable) - 1,
            "ok",
        )
    return output


def compute_path_label(
    series: list[dict[str, Any]],
    start_index: int,
    start_price: float,
    horizon: int = 20,
    up_threshold: float = 0.10,
    down_threshold: float = 0.05,
    include_start_day: bool = True,
) -> PathResult:
    suffix = "_total_return" if "high_total_return" in series[start_index] else "_qfq"
    begin = start_index if include_start_day else start_index + 1
    for row in series[begin : begin + horizon]:
        up = row[f"high{suffix}"] >= start_price * (1 + up_threshold)
        down = row[f"low{suffix}"] <= start_price * (1 - down_threshold)
        if up and down:
            return PathResult(False, None, row["date"], "failed", "same-day-double-hit")
        if down:
            return PathResult(False, None, row["date"], "failed", "downside-hit-first")
        if up:
            return PathResult(True, row["date"], None, "success", "upside-hit-first")
    return PathResult(False, None, None, "failed", "no-upside-hit")


def compute_drawdown_label(
    series: list[dict[str, Any]],
    start_index: int,
    start_price: float,
    horizon: int,
    threshold: float,
) -> DrawdownResult:
    suffix = "_total_return" if "close_total_return" in series[start_index] else "_qfq"
    peak = start_price
    peak_date = series[start_index]["date"]
    worst = 0.0
    worst_date = None
    worst_peak_date = peak_date
    for row in series[start_index : start_index + horizon]:
        close = float(row[f"close{suffix}"])
        if close > peak:
            peak = close
            peak_date = row["date"]
        drawdown = close / peak - 1
        if drawdown < worst:
            worst = drawdown
            worst_date = row["date"]
            worst_peak_date = peak_date
    return DrawdownResult(worst, worst <= -threshold, worst_date, worst_peak_date, "ok")


def compute_label_maturity_date(
    trading_dates: list[date], entry_index: int, horizon: int, settlement_buffer: int = 0
) -> date | None:
    target = entry_index + horizon + settlement_buffer
    return trading_dates[target] if target < len(trading_dates) else None


def cluster_independent_periods(
    samples: list[dict[str, Any]], gap_days: int = 7
) -> IndependentPeriodsResult:
    within_stock: list[dict[str, Any]] = []
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for sample in samples:
        groups.setdefault((sample["stock"], sample["condition"]), []).append(sample)
    for (_, condition), items in groups.items():
        items.sort(key=lambda item: item["end_date"])
        for item in items:
            if not within_stock or within_stock[-1]["stock"] != item["stock"] or (
                item["end_date"] - within_stock[-1]["end_date"]
            ).days > gap_days:
                within_stock.append({**item, "condition": condition})
            else:
                within_stock[-1]["end_date"] = item["end_date"]
    clusters: list[dict[str, Any]] = []
    for condition in sorted({item["condition"] for item in within_stock}):
        items = sorted(
            (item for item in within_stock if item["condition"] == condition),
            key=lambda item: item["end_date"],
        )
        for item in items:
            if not clusters or clusters[-1]["condition"] != condition or (
                item["end_date"] - clusters[-1]["end_date"]
            ).days > gap_days:
                clusters.append(
                    {
                        "condition": condition,
                        "start_date": item["end_date"],
                        "end_date": item["end_date"],
                        "stocks": {item["stock"]},
                    }
                )
            else:
                clusters[-1]["end_date"] = item["end_date"]
                clusters[-1]["stocks"].add(item["stock"])
    for cluster in clusters:
        cluster["stock_count"] = len(cluster.pop("stocks"))
    return IndependentPeriodsResult(len(clusters), clusters)

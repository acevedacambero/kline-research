from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from ..storage import atomic_write_parquet

from .core import (
    compute_drawdown_label,
    compute_forward_labels,
    compute_label_maturity_date,
    compute_path_label,
    resolve_executable_entry,
    resolve_executable_exit,
    sample_eligibility,
)
from .market_rules import is_no_limit_session


def filter_mature_samples(samples: list[dict[str, Any]], as_of_date: date):
    return [
        sample
        for sample in samples
        if sample["signal_date"] <= as_of_date
        and sample["label_maturity_date"] <= as_of_date
    ]


@dataclass(frozen=True)
class LabelStoreReport:
    status: str
    path: str
    rows: int


class LabelDatasetStore:
    def __init__(self, output_root: Path):
        self.output_root = Path(output_root)

    def write(
        self, exchange: str, code: str, rows: list[dict[str, Any]]
    ) -> LabelStoreReport:
        if not rows:
            return LabelStoreReport("empty", "", 0)
        snapshot = rows[0]["snapshot_version"]
        path = (
            self.output_root
            / "data-foundation-v1"
            / "labels"
            / snapshot
            / exchange
            / f"{code}.parquet"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_parquet(pd.DataFrame(rows), path)
        return LabelStoreReport("written", str(path), len(rows))


class BatchLabelBuilder:
    def __init__(
        self,
        sample_step: int = 5,
        horizons: Iterable[int] = (5, 10, 20, 60),
        max_entry_delay: int = 3,
        max_exit_delay: int = 3,
    ):
        self.sample_step = sample_step
        self.horizons = tuple(sorted(horizons))
        self.max_entry_delay = max_entry_delay
        self.max_exit_delay = max_exit_delay

    def build(
        self,
        exchange: str,
        code: str,
        bars: list[dict[str, Any]],
        benchmark: list[dict[str, Any]],
        snapshot_version: str,
        *,
        st_status: bool = False,
    ) -> list[dict[str, Any]]:
        if not bars or not benchmark:
            return []
        max_horizon = max(self.horizons)
        trading_dates = [bar["date"] for bar in bars]
        benchmark_date_index = {
            bar["date"]: index for index, bar in enumerate(benchmark)
        }
        listing_date = bars[0]["date"]
        no_limit_indices = {
            index
            for index, bar in enumerate(bars[:5])
            if is_no_limit_session(exchange, code, listing_date, index, bar["date"])
        }
        stop = len(bars) - max_horizon - self.max_entry_delay - self.max_exit_delay
        rows: list[dict[str, Any]] = []
        for signal_index in range(250, max(250, stop), self.sample_step):
            eligibility = sample_eligibility(bars, signal_index, rights_status="ok")
            if not eligibility.eligible:
                continue
            entry = resolve_executable_entry(
                bars,
                signal_index,
                code=code,
                exchange=exchange,
                st_status=st_status,
                max_delay=self.max_entry_delay,
                no_limit_indices=no_limit_indices,
            )
            if not entry.executable or entry.entry_index is None:
                continue
            entry_basis = float(bars[entry.entry_index].get(
                "open_total_return", bars[entry.entry_index]["open_qfq"]
            ))
            signal_basis = float(bars[signal_index].get(
                "close_total_return", bars[signal_index]["close_qfq"]
            ))
            if entry_basis <= 0 or signal_basis <= 0:
                continue
            labels = compute_forward_labels(
                bars, benchmark, signal_index, entry.entry_index, self.horizons,
                benchmark_date_index,
            )
            exits = {
                horizon: resolve_executable_exit(
                    bars, entry.entry_index + horizon, code=code,
                    exchange=exchange, st_status=st_status,
                    max_delay=self.max_exit_delay,
                )
                for horizon in self.horizons
            }
            maturity_dates = {
                horizon: compute_label_maturity_date(
                    trading_dates, entry.entry_index, horizon
                )
                for horizon in self.horizons
            }
            if any(value is None for value in maturity_dates.values()):
                continue
            path_start = entry_basis
            path = compute_path_label(bars, entry.entry_index, path_start)
            drawdown = compute_drawdown_label(
                bars, entry.entry_index, path_start, 20, 0.08
            )
            row: dict[str, Any] = {
                "exchange": exchange,
                "code": code,
                "signal_index": signal_index,
                "signal_date": bars[signal_index]["date"],
                "entry_index": entry.entry_index,
                "entry_date": entry.entry_date,
                "entry_delay": entry.entry_delay,
                "entry_price_raw": entry.entry_price,
                "path_success_p20": path.success,
                "path_reason_p20": path.reason,
                "max_drawdown_p20": drawdown.max_drawdown,
                "drawdown_risk_p20": drawdown.hit_risk,
                "label_maturity_date": max(
                    exit_result.exit_date or maturity_dates[horizon]
                    for horizon, exit_result in exits.items()
                ),
                "snapshot_version": snapshot_version,
                "factor_version": bars[0].get("factor_version", "unknown"),
                "label_definition_version": "daily-v2-exit-delay",
                "limit_rule_version": "cn-equity-v1",
                "sample_step": self.sample_step,
                "st_status_approx": st_status,
            }
            for horizon, label in labels.items():
                prefix = f"p{horizon}"
                for key, value in asdict(label).items():
                    if key != "horizon":
                        row[f"{prefix}_{key}"] = value
                row[f"{prefix}_maturity_date"] = maturity_dates[horizon]
                exit_result = exits[horizon]
                row[f"{prefix}_exit_status"] = exit_result.status
                row[f"{prefix}_exit_date"] = exit_result.exit_date
                row[f"{prefix}_exit_delay"] = exit_result.exit_delay
                row[f"{prefix}_delayed_executable_return"] = (
                    exit_result.exit_price
                    / entry_basis
                    - 1
                    if exit_result.executable and exit_result.exit_price is not None
                    else None
                )
            rows.append(row)
        return rows

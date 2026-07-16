from __future__ import annotations

from typing import Any, Sequence

import numpy as np
import pandas as pd


DRIFT_DEFINITION_VERSION = "feature-drift-v1"
DEFAULT_DRIFT_COLUMNS = (
    "score",
    "bullish_alignment",
    "return_20",
    "volume_ratio_5",
    "volatility_20",
)


def _psi(reference: pd.Series, recent: pd.Series, bins: int = 10) -> float | None:
    reference_values = pd.to_numeric(reference, errors="coerce").dropna().to_numpy(float)
    recent_values = pd.to_numeric(recent, errors="coerce").dropna().to_numpy(float)
    if len(reference_values) < 10 or len(recent_values) < 5:
        return None
    edges = np.unique(np.quantile(reference_values, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        center = float(np.mean(reference_values))
        edges = np.array([-np.inf, center, np.inf])
    else:
        edges[0], edges[-1] = -np.inf, np.inf
    reference_share = np.histogram(reference_values, bins=edges)[0] / len(reference_values)
    recent_share = np.histogram(recent_values, bins=edges)[0] / len(recent_values)
    reference_share = np.clip(reference_share, 1e-6, None)
    recent_share = np.clip(recent_share, 1e-6, None)
    return float(
        np.sum((recent_share - reference_share) * np.log(recent_share / reference_share))
    )


def _metric(reference: pd.DataFrame, recent: pd.DataFrame, column: str) -> dict[str, Any]:
    reference_values = pd.to_numeric(reference[column], errors="coerce")
    recent_values = pd.to_numeric(recent[column], errors="coerce")
    reference_std = (
        float(reference_values.std()) if reference_values.notna().sum() > 1 else 0.0
    )
    mean_shift = (
        abs(float(recent_values.mean()) - float(reference_values.mean())) / reference_std
        if reference_std > 0 and recent_values.notna().any() and reference_values.notna().any()
        else None
    )
    psi = _psi(reference_values, recent_values)
    missing_delta = float(recent_values.isna().mean() - reference_values.isna().mean())
    severity = "stable"
    if (
        (psi is not None and psi >= 0.25)
        or (mean_shift is not None and mean_shift >= 0.5)
        or missing_delta >= 0.1
    ):
        severity = "drift"
    elif (
        (psi is not None and psi >= 0.1)
        or (mean_shift is not None and mean_shift >= 0.25)
        or missing_delta >= 0.05
    ):
        severity = "watch"
    return {
        "column": column,
        "status": severity,
        "referenceCount": int(reference_values.notna().sum()),
        "recentCount": int(recent_values.notna().sum()),
        "referenceMean": (
            None if not reference_values.notna().any() else float(reference_values.mean())
        ),
        "recentMean": None if not recent_values.notna().any() else float(recent_values.mean()),
        "standardizedMeanShift": mean_shift,
        "populationStabilityIndex": psi,
        "missingRateDelta": missing_delta,
    }


def _overall_status(metrics: list[dict[str, Any]]) -> str:
    if any(item["status"] == "drift" for item in metrics):
        return "drift"
    if any(item["status"] == "watch" for item in metrics):
        return "watch"
    return "stable"


def compute_feature_drift(
    rows: pd.DataFrame | list[dict],
    *,
    recent_days: int = 60,
    reference_days: int = 250,
    columns: Sequence[str] = DEFAULT_DRIFT_COLUMNS,
) -> dict[str, Any]:
    frame = pd.DataFrame(rows).copy()
    available = [column for column in columns if column in frame.columns]
    if "date" not in frame or not available:
        return {
            "version": DRIFT_DEFINITION_VERSION,
            "status": "insufficient_data",
            "metrics": [],
            "segments": [],
            "warnings": ["缺少日期或监控字段"],
        }
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.date
    frame = frame.dropna(subset=["date"]).sort_values("date")
    dates = sorted(frame["date"].unique())
    recent_dates = set(dates[-recent_days:])
    reference_dates = set(dates[-(recent_days + reference_days) : -recent_days])
    reference = frame[frame["date"].isin(reference_dates)]
    recent = frame[frame["date"].isin(recent_dates)]
    if reference.empty or recent.empty:
        return {
            "version": DRIFT_DEFINITION_VERSION,
            "status": "insufficient_data",
            "metrics": [],
            "segments": [],
            "warnings": ["基准窗口或近期窗口样本不足"],
        }

    metrics = [_metric(reference, recent, column) for column in available]
    segments = []
    if "exchange" in frame:
        for exchange in sorted(frame["exchange"].dropna().unique()):
            reference_part = reference[reference["exchange"] == exchange]
            recent_part = recent[recent["exchange"] == exchange]
            if not reference_part.empty and not recent_part.empty:
                segment_metrics = [
                    _metric(reference_part, recent_part, column) for column in available
                ]
                segments.append(
                    {
                        "exchange": exchange,
                        "status": _overall_status(segment_metrics),
                        "metrics": segment_metrics,
                    }
                )

    return {
        "version": DRIFT_DEFINITION_VERSION,
        "status": _overall_status(metrics),
        "referenceWindow": {
            "startDate": min(reference_dates),
            "endDate": max(reference_dates),
            "tradingDays": len(reference_dates),
            "rows": len(reference),
        },
        "recentWindow": {
            "startDate": min(recent_dates),
            "endDate": max(recent_dates),
            "tradingDays": len(recent_dates),
            "rows": len(recent),
        },
        "thresholds": {
            "psiWatch": 0.1,
            "psiDrift": 0.25,
            "meanShiftWatch": 0.25,
            "meanShiftDrift": 0.5,
        },
        "metrics": metrics,
        "segments": segments,
        "warnings": [],
    }

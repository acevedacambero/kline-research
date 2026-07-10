from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd


VALIDATION_DEFINITION_VERSION = "p4-single-factor-v1"


def _empty_result(
    factor_column: str,
    label_column: str,
    buckets: int,
    *,
    missing_columns: list[str] | None = None,
    dropped: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {
        "version": VALIDATION_DEFINITION_VERSION,
        "factorColumn": factor_column,
        "labelColumn": label_column,
        "bucketCount": buckets,
        "sampleCount": 0,
        "rankCorrelation": None,
        "buckets": [],
        "missingColumns": missing_columns or [],
        "dropped": dropped or {"unusable": 0, "immature": 0, "missing": 0},
    }


def _missing_columns(
    scores: pd.DataFrame, labels: pd.DataFrame, factor_column: str, label_column: str
) -> list[str]:
    required_scores = {"exchange", "code", "date", factor_column}
    required_labels = {"exchange", "code", "signal_date", label_column}
    missing = [
        f"score.{column}" for column in sorted(required_scores.difference(scores.columns))
    ]
    missing.extend(
        f"label.{column}" for column in sorted(required_labels.difference(labels.columns))
    )
    return missing


def validate_single_factor(
    scores: pd.DataFrame | list[dict],
    labels: pd.DataFrame | list[dict],
    *,
    factor_column: str,
    label_column: str,
    buckets: int = 5,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    score_frame = pd.DataFrame(scores).copy()
    label_frame = pd.DataFrame(labels).copy()
    bucket_count = max(1, int(buckets))
    missing = _missing_columns(score_frame, label_frame, factor_column, label_column)
    if missing:
        return _empty_result(
            factor_column, label_column, bucket_count, missing_columns=missing
        )

    score_frame["date"] = pd.to_datetime(score_frame["date"]).dt.date
    label_frame["signal_date"] = pd.to_datetime(label_frame["signal_date"]).dt.date
    score_frame[factor_column] = pd.to_numeric(
        score_frame[factor_column], errors="coerce"
    )
    label_frame[label_column] = pd.to_numeric(label_frame[label_column], errors="coerce")

    merged = score_frame.merge(
        label_frame,
        left_on=["exchange", "code", "date"],
        right_on=["exchange", "code", "signal_date"],
        how="inner",
        suffixes=("_score", "_label"),
    )
    if merged.empty:
        return _empty_result(factor_column, label_column, bucket_count)

    dropped = {"unusable": 0, "immature": 0, "missing": 0}
    if "usable" in merged:
        unusable = ~merged["usable"].fillna(False).astype(bool)
        dropped["unusable"] = int(unusable.sum())
        merged = merged.loc[~unusable].copy()
    if as_of_date is not None and "label_maturity_date" in merged:
        maturity = pd.to_datetime(merged["label_maturity_date"]).dt.date
        immature = maturity > as_of_date
        dropped["immature"] = int(immature.sum())
        merged = merged.loc[~immature].copy()

    missing_values = merged[factor_column].isna() | merged[label_column].isna()
    dropped["missing"] = int(missing_values.sum())
    merged = merged.loc[~missing_values].copy()
    if merged.empty:
        return _empty_result(
            factor_column, label_column, bucket_count, dropped=dropped
        )

    actual_buckets = min(bucket_count, len(merged))
    merged["bucket"] = pd.qcut(
        merged[factor_column].rank(method="first"),
        q=actual_buckets,
        labels=False,
        duplicates="drop",
    )
    bucket_rows = []
    for bucket, group in merged.groupby("bucket", sort=True):
        labels_in_bucket = group[label_column]
        bucket_rows.append(
            {
                "bucket": int(bucket) + 1,
                "count": int(len(group)),
                "minFactor": float(group[factor_column].min()),
                "maxFactor": float(group[factor_column].max()),
                "avgFactor": float(group[factor_column].mean()),
                "avgLabel": float(labels_in_bucket.mean()),
                "medianLabel": float(labels_in_bucket.median()),
                "winRate": float((labels_in_bucket > 0).mean()),
                "pathSuccessRate": (
                    float(group["path_success_p20"].fillna(False).astype(bool).mean())
                    if "path_success_p20" in group else None
                ),
                "avgMaxDrawdown": (
                    float(pd.to_numeric(group["max_drawdown_p20"], errors="coerce").mean())
                    if "max_drawdown_p20" in group else None
                ),
            }
        )
    correlation = merged[factor_column].rank().corr(merged[label_column].rank())
    return {
        "version": VALIDATION_DEFINITION_VERSION,
        "factorColumn": factor_column,
        "labelColumn": label_column,
        "bucketCount": actual_buckets,
        "sampleCount": int(len(merged)),
        "rankCorrelation": None if pd.isna(correlation) else float(correlation),
        "buckets": bucket_rows,
        "missingColumns": [],
        "dropped": dropped,
    }

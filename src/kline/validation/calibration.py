from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd


CALIBRATION_DEFINITION_VERSION = "p5-score-calibration-v1"


def calibrate_score(
    scores: pd.DataFrame | list[dict],
    labels: pd.DataFrame | list[dict],
    *,
    label_column: str = "p20_executable_return",
    buckets: int = 10,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    score_frame = pd.DataFrame(scores).copy()
    label_frame = pd.DataFrame(labels).copy()
    bucket_count = max(1, int(buckets))
    required_scores = {"exchange", "code", "date", "score"}
    required_labels = {"exchange", "code", "signal_date", label_column}
    missing = [f"score.{x}" for x in sorted(required_scores - set(score_frame.columns))]
    missing.extend(f"label.{x}" for x in sorted(required_labels - set(label_frame.columns)))
    base = {
        "version": CALIBRATION_DEFINITION_VERSION,
        "labelColumn": label_column,
        "bucketCount": bucket_count,
        "sampleCount": 0,
        "buckets": [],
        "missingColumns": missing,
        "dropped": {"unusable": 0, "immature": 0, "missing": 0},
        "reliability": {"status": "insufficient_sample", "warnings": ["暂无可用成熟样本"]},
    }
    if missing:
        return base
    score_frame["date"] = pd.to_datetime(score_frame["date"]).dt.date
    available_as_of = score_frame["date"].max()
    label_frame["signal_date"] = pd.to_datetime(label_frame["signal_date"]).dt.date
    score_frame["score"] = pd.to_numeric(score_frame["score"], errors="coerce")
    label_frame[label_column] = pd.to_numeric(label_frame[label_column], errors="coerce")
    merged = score_frame.merge(label_frame, left_on=["exchange", "code", "date"],
                               right_on=["exchange", "code", "signal_date"], how="inner")
    dropped = base["dropped"]
    if "usable" in merged:
        mask = ~merged["usable"].fillna(False).astype(bool)
        dropped["unusable"] = int(mask.sum())
        merged = merged.loc[~mask].copy()
    effective_as_of = as_of_date or available_as_of
    merged = merged.loc[merged["date"] <= effective_as_of].copy()
    if "label_maturity_date" in merged:
        mask = pd.to_datetime(merged["label_maturity_date"]).dt.date > effective_as_of
        dropped["immature"] = int(mask.sum())
        merged = merged.loc[~mask].copy()
    if merged.empty:
        return {**base, "dropped": dropped}
    mask = merged["score"].isna() | merged[label_column].isna()
    dropped["missing"] = int(mask.sum())
    merged = merged.loc[~mask].copy()
    if merged.empty:
        return {**base, "dropped": dropped}
    actual = min(bucket_count, len(merged))
    merged["bucket"] = pd.qcut(merged["score"].rank(method="first"), q=actual, labels=False)
    rows = []
    for bucket, group in merged.groupby("bucket", sort=True):
        result = group[label_column]
        rows.append({
            "bucket": int(bucket) + 1,
            "count": int(len(group)),
            "minScore": float(group["score"].min()),
            "maxScore": float(group["score"].max()),
            "avgScore": float(group["score"].mean()),
            "observedProbability": float((result > 0).mean()),
            "avgLabel": float(result.mean()),
        })
    probabilities = [row["observedProbability"] for row in rows]
    monotonic = all(left <= right for left, right in zip(probabilities, probabilities[1:]))
    warnings = []
    if len(merged) < 30:
        warnings.append("样本少于 30，概率仅供探索")
    if not monotonic:
        warnings.append("分桶胜率非单调，暂不视为可靠校准")
    reliability = {"status": "usable" if len(merged) >= 30 and monotonic else "review",
                   "warnings": warnings}
    return {**base, "bucketCount": actual, "sampleCount": int(len(merged)),
            "buckets": rows, "missingColumns": [], "dropped": dropped,
            "reliability": reliability}

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from ..validation.isolation import purged_time_split


BASELINE_MODEL_VERSION = "p7-score-logistic-v1"
WALK_FORWARD_MODEL_VERSION = "p7-walk-forward-v2-nonoverlap"


def binary_auc(labels: np.ndarray, predictions: np.ndarray) -> float | None:
    positives = labels == 1
    positive_count = int(positives.sum())
    negative_count = int((~positives).sum())
    if not positive_count or not negative_count:
        return None
    ranks = pd.Series(predictions).rank(method="average").to_numpy()
    rank_sum = float(ranks[positives].sum())
    return (rank_sum - positive_count * (positive_count + 1) / 2) / (
        positive_count * negative_count
    )


def walk_forward_score_baseline(
    scores: pd.DataFrame | list[dict],
    labels: pd.DataFrame | list[dict],
    *,
    label_column: str = "p20_executable_return",
    folds: int = 3,
    embargo_days: int = 0,
) -> dict[str, Any]:
    sf = pd.DataFrame(scores).copy()
    lf = pd.DataFrame(labels).copy()
    if "date" not in sf or not {"exchange", "code", "signal_date", label_column}.issubset(
        lf.columns
    ):
        return {
            "version": WALK_FORWARD_MODEL_VERSION,
            "folds": [],
            "averageAuc": None,
            "averageAccuracy": None,
            "warnings": ["缺少评分日期"],
        }
    sf["date"] = pd.to_datetime(sf["date"], errors="coerce").dt.date
    lf["signal_date"] = pd.to_datetime(lf["signal_date"], errors="coerce").dt.date
    available_as_of = sf["date"].dropna().max()
    if "label_maturity_date" in lf and available_as_of is not None:
        maturity = pd.to_datetime(lf["label_maturity_date"], errors="coerce").dt.date
        lf = lf.loc[maturity <= available_as_of]
    eligible_dates = sf[["exchange", "code", "date"]].merge(
        lf[["exchange", "code", "signal_date"]],
        left_on=["exchange", "code", "date"],
        right_on=["exchange", "code", "signal_date"],
    )["date"]
    dates = sorted(eligible_dates.dropna().unique())
    fold_count = max(2, min(5, int(folds)))
    cutoffs = []
    for index in range(fold_count):
        # Reserve wide forward windows so long-horizon labels can mature inside
        # each fold instead of being excluded by the anti-leakage cutoff.
        position = int(len(dates) * (0.2 + index * 0.5 / max(1, fold_count - 1)))
        if dates:
            cutoffs.append(dates[min(len(dates) - 1, position)])
    rows = []
    unique_cutoffs = list(dict.fromkeys(cutoffs))
    for index, cutoff in enumerate(unique_cutoffs):
        test_until = (
            unique_cutoffs[index + 1]
            if index + 1 < len(unique_cutoffs)
            else (dates[-1] if dates else cutoff)
        )
        result = train_score_baseline(
            scores,
            labels,
            label_column=label_column,
            train_until=cutoff,
            test_until=test_until,
            embargo_days=embargo_days,
        )
        rows.append(
            {
                "trainUntil": cutoff,
                "testUntil": test_until,
                "status": result["status"],
                "trainCount": result["trainCount"],
                "testCount": result["testCount"],
                "auc": result["auc"],
                "accuracy": result["accuracy"],
                "isolation": result.get("isolation"),
            }
        )
    aucs = [row["auc"] for row in rows if row["auc"] is not None]
    accuracies = [row["accuracy"] for row in rows if row["accuracy"] is not None]
    return {
        "version": WALK_FORWARD_MODEL_VERSION,
        "folds": rows,
        "averageAuc": float(np.mean(aucs)) if aucs else None,
        "averageAccuracy": float(np.mean(accuracies)) if accuracies else None,
        "warnings": [] if aucs else ["没有足够成熟样本完成 walk-forward"],
        "isolationRuleVersion": "purged-embargo-v1",
        "embargoDays": embargo_days,
    }


def train_score_baseline(
    scores: pd.DataFrame | list[dict],
    labels: pd.DataFrame | list[dict],
    *,
    label_column: str = "p20_executable_return",
    train_until: date | None = None,
    test_until: date | None = None,
    embargo_days: int = 0,
) -> dict[str, Any]:
    base = {
        "version": BASELINE_MODEL_VERSION,
        "labelColumn": label_column,
        "status": "insufficient_data",
        "trainCount": 0,
        "testCount": 0,
        "positiveRate": None,
        "testPositiveRate": None,
        "accuracy": None,
        "auc": None,
        "intercept": None,
        "coefficient": None,
        "warnings": [],
    }
    sf, lf = pd.DataFrame(scores).copy(), pd.DataFrame(labels).copy()
    required = {"exchange", "code", "date", "score"}
    required_label = {"exchange", "code", "signal_date", label_column}
    missing = sorted((required - set(sf.columns)) | (required_label - set(lf.columns)))
    if missing:
        base["warnings"] = [f"缺少字段: {', '.join(missing)}"]
        return base
    sf["date"] = pd.to_datetime(sf["date"]).dt.date
    available_as_of = sf["date"].max()
    lf["signal_date"] = pd.to_datetime(lf["signal_date"]).dt.date
    merged = sf.merge(
        lf, left_on=["exchange", "code", "date"], right_on=["exchange", "code", "signal_date"]
    )
    if "usable" in merged:
        merged = merged.loc[merged["usable"].fillna(False).astype(bool)]
    merged["score"] = pd.to_numeric(merged["score"], errors="coerce")
    merged[label_column] = pd.to_numeric(merged[label_column], errors="coerce")
    merged = merged.dropna(subset=["score", label_column]).sort_values("date")
    if train_until is None:
        unique_dates = sorted(merged["date"].unique())
        train_until = (
            unique_dates[max(0, int(len(unique_dates) * 0.7) - 1)] if unique_dates else None
        )
    if train_until is None:
        base["warnings"] = ["没有可用成熟样本"]
        return base
    evaluation_end = test_until or available_as_of
    train, test, isolation = purged_time_split(
        merged,
        train_until=train_until,
        evaluation_end=evaluation_end,
        embargo_days=embargo_days,
    )
    base["isolation"] = isolation
    base["trainCount"], base["testCount"] = int(len(train)), int(len(test))
    if len(train) < 20 or len(test) < 5:
        base["warnings"] = ["训练集至少 20 条、测试集至少 5 条"]
        return base
    x = (train["score"].to_numpy(float) - 50.0) / 25.0
    y = (train[label_column].to_numpy(float) > 0).astype(float)
    intercept, coefficient = 0.0, 0.0
    for _ in range(800):
        z = intercept + coefficient * x
        p = 1.0 / (1.0 + np.exp(np.clip(-z, -35, 35)))
        intercept += 0.03 * float((y - p).mean())
        coefficient += 0.03 * float(((y - p) * x).mean())
    xt = (test["score"].to_numpy(float) - 50.0) / 25.0
    yt = (test[label_column].to_numpy(float) > 0).astype(float)
    pred = 1.0 / (1.0 + np.exp(np.clip(-(intercept + coefficient * xt), -35, 35)))
    predicted = pred >= 0.5
    accuracy = float((predicted == yt).mean())
    auc = binary_auc(yt, pred)
    warnings = []
    if coefficient <= 0:
        warnings.append("分数系数非正，评分方向未获得样本外支持")
    if auc is not None and auc < 0.5:
        warnings.append("样本外 AUC 低于 0.5，需要复核")
    return {
        **base,
        "status": "trained" if not warnings else "review",
        "positiveRate": float(y.mean()),
        "testPositiveRate": float(yt.mean()),
        "accuracy": accuracy,
        "auc": auc,
        "intercept": float(intercept),
        "coefficient": float(coefficient),
        "trainUntil": train_until,
        "testUntil": evaluation_end,
        "isolation": isolation,
        "warnings": warnings,
    }

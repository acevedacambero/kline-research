from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd


BASELINE_MODEL_VERSION = "p7-score-logistic-v1"


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


def train_score_baseline(
    scores: pd.DataFrame | list[dict],
    labels: pd.DataFrame | list[dict],
    *,
    label_column: str = "p20_executable_return",
    train_until: date | None = None,
) -> dict[str, Any]:
    base = {"version": BASELINE_MODEL_VERSION, "labelColumn": label_column,
            "status": "insufficient_data", "trainCount": 0, "testCount": 0,
            "positiveRate": None, "testPositiveRate": None, "accuracy": None,
            "auc": None, "intercept": None, "coefficient": None,
            "warnings": []}
    sf, lf = pd.DataFrame(scores).copy(), pd.DataFrame(labels).copy()
    required = {"exchange", "code", "date", "score"}
    required_label = {"exchange", "code", "signal_date", label_column}
    missing = sorted((required - set(sf.columns)) | (required_label - set(lf.columns)))
    if missing:
        base["warnings"] = [f"缺少字段: {', '.join(missing)}"]
        return base
    sf["date"] = pd.to_datetime(sf["date"]).dt.date
    lf["signal_date"] = pd.to_datetime(lf["signal_date"]).dt.date
    merged = sf.merge(lf, left_on=["exchange", "code", "date"], right_on=["exchange", "code", "signal_date"])
    if "usable" in merged:
        merged = merged.loc[merged["usable"].fillna(False).astype(bool)]
    merged["score"] = pd.to_numeric(merged["score"], errors="coerce")
    merged[label_column] = pd.to_numeric(merged[label_column], errors="coerce")
    merged = merged.dropna(subset=["score", label_column]).sort_values("date")
    if train_until is None:
        unique_dates = sorted(merged["date"].unique())
        train_until = unique_dates[max(0, int(len(unique_dates) * 0.7) - 1)] if unique_dates else None
    if train_until is None:
        base["warnings"] = ["没有可用成熟样本"]
        return base
    train, test = merged.loc[merged["date"] <= train_until], merged.loc[merged["date"] > train_until]
    if "label_maturity_date" in train:
        maturity = pd.to_datetime(train["label_maturity_date"], errors="coerce").dt.date
        train = train.loc[maturity <= train_until]
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
    return {**base, "status": "trained" if not warnings else "review", "positiveRate": float(y.mean()),
            "testPositiveRate": float(yt.mean()), "accuracy": accuracy,
            "auc": auc,
            "intercept": float(intercept), "coefficient": float(coefficient),
            "trainUntil": train_until, "warnings": warnings}

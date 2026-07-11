from __future__ import annotations

from datetime import date
from typing import Any, Sequence

import numpy as np
import pandas as pd

MULTI_FEATURE_MODEL_VERSION = "p7-multifeature-logistic-v1"
DEFAULT_FEATURE_COLUMNS = ("score", "bullish_alignment", "return_20", "volume_ratio_5", "volatility_20")


def train_multifeature_baseline(scores: pd.DataFrame | list[dict], labels: pd.DataFrame | list[dict], features: pd.DataFrame | list[dict], *, label_column: str = "p20_executable_return", train_until: date | None = None, feature_columns: Sequence[str] = DEFAULT_FEATURE_COLUMNS) -> dict[str, Any]:
    sf = pd.DataFrame(scores).copy()
    ff = pd.DataFrame(features).copy()
    lf = pd.DataFrame(labels).copy()
    base = {"version": MULTI_FEATURE_MODEL_VERSION, "labelColumn": label_column, "featureColumns": list(feature_columns), "status": "insufficient_data", "trainCount": 0, "testCount": 0, "accuracy": None, "auc": None, "weights": {}, "warnings": []}
    if not {"exchange", "code", "date", *feature_columns}.issubset(set(sf.columns) | set(ff.columns)):
        base["warnings"] = ["缺少 P2/P3 特征字段"]
        return base
    if not {"exchange", "code", "signal_date", label_column}.issubset(lf.columns):
        base["warnings"] = ["缺少标签字段"]
        return base
    sf["date"] = pd.to_datetime(sf["date"]).dt.date
    ff["date"] = pd.to_datetime(ff["date"]).dt.date
    lf["signal_date"] = pd.to_datetime(lf["signal_date"]).dt.date
    merged = sf.merge(ff, on=["exchange", "code", "date"], suffixes=("", "_feature"))
    merged = merged.merge(lf, left_on=["exchange", "code", "date"], right_on=["exchange", "code", "signal_date"])
    if "usable" in merged:
        merged = merged.loc[merged["usable"].fillna(False).astype(bool)]
    for column in feature_columns:
        if column not in merged and f"{column}_feature" in merged:
            merged[column] = merged[f"{column}_feature"]
        merged[column] = pd.to_numeric(merged[column], errors="coerce")
    merged[label_column] = pd.to_numeric(merged[label_column], errors="coerce")
    merged = merged.dropna(subset=[*feature_columns, label_column]).sort_values("date")
    dates = sorted(merged["date"].unique())
    if train_until is None and dates:
        train_until = dates[max(0, int(len(dates) * 0.7) - 1)]
    if train_until is None:
        base["warnings"] = ["没有可用成熟样本"]
        return base
    train = merged.loc[merged["date"] <= train_until]
    test = merged.loc[merged["date"] > train_until]
    base["trainCount"] = int(len(train))
    base["testCount"] = int(len(test))
    if len(train) < 30 or len(test) < 10:
        base["warnings"] = ["训练集至少 30 条、测试集至少 10 条"]
        return base
    x = train[list(feature_columns)].to_numpy(float)
    xt = test[list(feature_columns)].to_numpy(float)
    mean = x.mean(axis=0)
    std = x.std(axis=0)
    std[std == 0] = 1
    x = (x - mean) / std
    xt = (xt - mean) / std
    y = (train[label_column].to_numpy(float) > 0).astype(float)
    yt = (test[label_column].to_numpy(float) > 0).astype(float)
    intercept = 0.0
    weights = np.zeros(x.shape[1])
    for _ in range(900):
        probability = 1 / (1 + np.exp(np.clip(-(intercept + x @ weights), -35, 35)))
        error = y - probability
        intercept += 0.02 * float(error.mean())
        weights += 0.02 * (error[:, None] * x).mean(axis=0)
    prediction = 1 / (1 + np.exp(np.clip(-(intercept + xt @ weights), -35, 35)))
    accuracy = float(((prediction >= 0.5) == yt).mean())
    rank = None if len(set(yt)) < 2 else pd.Series(prediction).rank().corr(pd.Series(yt).rank())
    auc = None if rank is None or pd.isna(rank) else float((rank + 1) / 2)
    warnings = ["样本外 AUC 低于 0.5，需要复核"] if auc is not None and auc < 0.5 else []
    return {**base, "status": "trained" if not warnings else "review", "trainUntil": train_until, "accuracy": accuracy, "auc": auc, "weights": {column: float(weight) for column, weight in zip(feature_columns, weights)}, "warnings": warnings}

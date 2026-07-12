from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd


BOOTSTRAP_SAMPLES = 400
BOOTSTRAP_MAX_OBSERVATIONS = 10_000


def bootstrap_interval(
    values,
    statistic: Callable[[np.ndarray], float] = np.mean,
    *,
    confidence: float = 0.95,
    seed: int = 20260713,
) -> dict[str, float | int] | None:
    clean = pd.to_numeric(pd.Series(values), errors="coerce").dropna().to_numpy(float)
    if clean.size < 2:
        return None
    rng = np.random.default_rng(seed)
    draw_size = min(clean.size, BOOTSTRAP_MAX_OBSERVATIONS)
    estimates = np.empty(BOOTSTRAP_SAMPLES, dtype=float)
    for index in range(BOOTSTRAP_SAMPLES):
        estimates[index] = statistic(rng.choice(clean, size=draw_size, replace=True))
    alpha = (1 - confidence) / 2
    lower, upper = np.quantile(estimates, [alpha, 1 - alpha])
    return {
        "lower": float(lower),
        "upper": float(upper),
        "confidence": confidence,
        "samples": BOOTSTRAP_SAMPLES,
    }


def bootstrap_rank_correlation_interval(
    factors,
    outcomes,
    *,
    confidence: float = 0.95,
    seed: int = 20260713,
) -> dict[str, float | int] | None:
    frame = pd.DataFrame({"factor": factors, "outcome": outcomes}).apply(
        pd.to_numeric, errors="coerce"
    ).dropna()
    if len(frame) < 3:
        return None
    values = frame.to_numpy(float)
    rng = np.random.default_rng(seed)
    draw_size = min(len(values), BOOTSTRAP_MAX_OBSERVATIONS)
    estimates = []
    for _ in range(BOOTSTRAP_SAMPLES):
        sample = values[rng.integers(0, len(values), size=draw_size)]
        correlation = pd.Series(sample[:, 0]).rank().corr(
            pd.Series(sample[:, 1]).rank()
        )
        if not pd.isna(correlation):
            estimates.append(float(correlation))
    if not estimates:
        return None
    alpha = (1 - confidence) / 2
    lower, upper = np.quantile(estimates, [alpha, 1 - alpha])
    return {
        "lower": float(lower),
        "upper": float(upper),
        "confidence": confidence,
        "samples": len(estimates),
    }

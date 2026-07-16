from __future__ import annotations

from datetime import date, timedelta

import pandas as pd


ISOLATION_RULE_VERSION = "purged-embargo-v1"


def purged_time_split(
    frame: pd.DataFrame,
    *,
    train_until: date,
    evaluation_end: date,
    date_column: str = "date",
    maturity_column: str = "label_maturity_date",
    embargo_days: int = 0,
):
    dates = pd.to_datetime(frame[date_column], errors="coerce").dt.date
    maturity = (
        pd.to_datetime(frame[maturity_column], errors="coerce").dt.date
        if maturity_column in frame
        else dates
    )
    test_after = train_until + timedelta(days=max(0, embargo_days))
    train_signal = dates <= train_until
    train_mature = maturity <= train_until
    test_signal = (dates > test_after) & (dates <= evaluation_end)
    test_mature = maturity <= evaluation_end
    train = frame.loc[train_signal & train_mature].copy()
    test = frame.loc[test_signal & test_mature].copy()
    audit = {
        "version": ISOLATION_RULE_VERSION,
        "trainUntil": train_until,
        "testAfter": test_after,
        "evaluationEnd": evaluation_end,
        "embargoDays": max(0, embargo_days),
        "purgedImmatureTrain": int((train_signal & ~train_mature).sum()),
        "embargoedSamples": int(((dates > train_until) & (dates <= test_after)).sum()),
        "immatureTest": int((test_signal & ~test_mature).sum()),
    }
    return train, test, audit

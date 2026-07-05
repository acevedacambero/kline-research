from __future__ import annotations

import pandas as pd


ADJUSTED_SUFFIXES = ("_qfq", "_hfq", "_total_return")


def merge_raw_segments(segments: list[tuple[str, pd.DataFrame]]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for priority, (provider, frame) in enumerate(segments):
        if any(str(column).endswith(ADJUSTED_SUFFIXES) for column in frame.columns):
            raise ValueError("cross-provider merge rejects adjusted columns; merge raw facts only")
        candidate = frame.copy()
        candidate["provider"] = provider
        candidate["provider_priority"] = priority
        frames.append(candidate)
    if not frames:
        return pd.DataFrame()
    merged = pd.concat(frames, ignore_index=True).sort_values(["date", "provider_priority"])
    return merged.drop_duplicates("date", keep="first").reset_index(drop=True)


class DerivedAdjustmentEngine:
    price_columns = ("open", "high", "low", "close")

    def derive(self, raw: pd.DataFrame, factors: pd.DataFrame) -> pd.DataFrame:
        if raw.empty:
            return raw.copy()
        result = raw.sort_values("date").reset_index(drop=True).copy()
        factor_table = factors.sort_values("date").copy()
        if factor_table.empty:
            raise ValueError("adjustment factor table is empty")
        result["date"] = pd.to_datetime(result["date"])
        factor_table["date"] = pd.to_datetime(factor_table["date"])
        effective = pd.merge_asof(
            result[["date"]], factor_table[["date", "qfq_factor", "hfq_factor"]],
            on="date", direction="backward",
        )
        if effective[["qfq_factor", "hfq_factor"]].isna().any().any():
            raise ValueError("adjustment factors do not cover the complete raw history")
        for column in self.price_columns:
            values = result[column].astype(float)
            result[f"{column}_qfq"] = values / effective["qfq_factor"].astype(float)
            result[f"{column}_hfq"] = values * effective["hfq_factor"].astype(float)
            result[f"{column}_total_return"] = result[f"{column}_hfq"]
        result["factor_version"] = self.factor_version(factor_table)
        result["date"] = result["date"].dt.date
        return result

    @staticmethod
    def factor_version(factors: pd.DataFrame) -> str:
        values = pd.util.hash_pandas_object(factors, index=True).values.tobytes()
        import hashlib

        return "factor-" + hashlib.sha256(values).hexdigest()[:16]

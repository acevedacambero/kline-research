from __future__ import annotations

from datetime import date
from typing import Protocol

import pandas as pd


SUPPORTED_EXCHANGES = ("sh", "sz")
PROVIDER_POLICY_VERSION = "sh-sz-tencent-sina-v1"
HISTORY_BACKFILL_VERSION = "history-backfill-v1"


class MarketNotSupportedError(ValueError):
    pass


class TencentSource(Protocol):
    def fetch_history(
        self, exchange: str, code: str, start_date: date, end_date: date
    ) -> pd.DataFrame: ...


class SinaSource(Protocol):
    def sina_raw_history(
        self, exchange: str, code: str, start_date: date, end_date: date
    ) -> pd.DataFrame: ...

    def sina_adjustment_factors(
        self, exchange: str, code: str
    ) -> pd.DataFrame: ...


class ProductionProviderPolicy:
    def __init__(self, tencent: TencentSource, sina: SinaSource) -> None:
        self.tencent = tencent
        self.sina = sina
        self.direct_available = True

    def fetch_bundle(
        self, exchange: str, code: str, start_date: date, end_date: date
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        exchange = exchange.lower().strip()
        if exchange not in SUPPORTED_EXCHANGES:
            raise MarketNotSupportedError(f"market not supported: {exchange or '<empty>'}")

        try:
            raw = self.tencent.fetch_history(exchange, code, start_date, end_date)
            raw_provider = "tencent-http"
        except Exception:
            self.direct_available = False
            raw = self.sina.sina_raw_history(
                exchange, code, start_date, end_date
            )
            raw_provider = "sina-akshare"

        factors = self.sina.sina_adjustment_factors(exchange, code)
        self._validate_factors(factors)

        raw.attrs.update(
            provider=raw_provider, provider_policy_version=PROVIDER_POLICY_VERSION
        )
        factors.attrs.update(
            provider="sina-akshare",
            provider_policy_version=PROVIDER_POLICY_VERSION,
        )
        return raw, factors

    def fetch_long_history_bundle(
        self, exchange: str, code: str, start_date: date, end_date: date
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        exchange = exchange.lower().strip()
        if exchange not in SUPPORTED_EXCHANGES:
            raise MarketNotSupportedError(f"market not supported: {exchange or '<empty>'}")
        raw = self.sina.sina_raw_history(exchange, code, start_date, end_date)
        factors = self.sina.sina_adjustment_factors(exchange, code)
        self._validate_factors(factors)
        raw.attrs.update(
            provider="sina-akshare", provider_policy_version=HISTORY_BACKFILL_VERSION
        )
        factors.attrs.update(
            provider="sina-akshare", provider_policy_version=HISTORY_BACKFILL_VERSION
        )
        return raw, factors

    @staticmethod
    def _validate_factors(factors: pd.DataFrame) -> None:
        required = {"date", "qfq_factor", "hfq_factor"}
        if (
            factors.empty
            or not required.issubset(factors.columns)
            or factors[list(required)].isna().any().any()
        ):
            raise ValueError("factor data is empty or incomplete")

    def index_history(
        self, exchange: str, start_date: date, end_date: date
    ) -> pd.DataFrame:
        exchange = exchange.lower().strip()
        if exchange not in SUPPORTED_EXCHANGES:
            raise MarketNotSupportedError(f"market not supported: {exchange or '<empty>'}")
        return self.tencent.index_history(exchange, start_date, end_date)

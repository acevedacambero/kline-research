from __future__ import annotations

from datetime import date
import time
from typing import Any

import pandas as pd

from .adjustment import merge_raw_segments


def infer_exchange(code: str) -> str:
    if code.startswith(("4", "8", "9")):
        return "bj"
    if code.startswith(("5", "6", "68")):
        return "sh"
    return "sz"


class AkShareSource:
    def __init__(
        self,
        client: Any | None = None,
        retries: int = 3,
        retry_delay: float = 0.5,
        chunk_years: int = 5,
    ):
        if client is None:
            import akshare as client_module

            client = client_module
        self.client = client
        self.retries = retries
        self.retry_delay = retry_delay
        self.chunk_years = chunk_years

    def _call(self, operation: str, function, **kwargs):
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                return function(**kwargs)
            except Exception as exc:
                last_error = exc
                if attempt < self.retries and self.retry_delay:
                    time.sleep(self.retry_delay * attempt)
        raise RuntimeError(
            f"{operation} failed after {self.retries} attempts: {last_error}"
        ) from last_error

    def list_securities(self) -> list[dict[str, str]]:
        frame = self._call("stock_info_a_code_name", self.client.stock_info_a_code_name)
        code_column = "code" if "code" in frame.columns else "证券代码"
        name_column = "name" if "name" in frame.columns else "证券简称"
        return [
            {"exchange": infer_exchange(code), "code": code, "name": str(row[name_column])}
            for _, row in frame.iterrows()
            if (code := str(row[code_column]).zfill(6)).isdigit()
        ]

    def stock_history(
        self, symbol: str, start_date: date, end_date: date, adjust: str = ""
    ) -> pd.DataFrame:
        segments: list[tuple[str, pd.DataFrame]] = []
        provider = "stock_zh_a_hist"
        primary_available = True
        chunk_start = start_date
        while chunk_start <= end_date:
            chunk_end = min(date(chunk_start.year + self.chunk_years - 1, 12, 31), end_date)
            try:
                if not primary_available:
                    raise RuntimeError("primary provider disabled after prior failure")
                frame = self._call(
                    "stock_zh_a_hist",
                    self.client.stock_zh_a_hist,
                    symbol=symbol,
                    period="daily",
                    start_date=chunk_start.strftime("%Y%m%d"),
                    end_date=chunk_end.strftime("%Y%m%d"),
                    adjust=adjust,
                )
            except RuntimeError:
                primary_available = False
                fallback = getattr(self.client, "stock_zh_a_daily", None)
                if not callable(fallback):
                    raise
                provider = "stock_zh_a_daily"
                frame = self._call(
                    provider,
                    fallback,
                    symbol=infer_exchange(symbol) + symbol,
                    start_date=chunk_start.strftime("%Y%m%d"),
                    end_date=chunk_end.strftime("%Y%m%d"),
                    adjust=adjust,
                )
            normalized = self._normalize_history(frame)
            normalized["fields_partial"] = False
            segments.append(("eastmoney" if primary_available else "sina", normalized))
            chunk_start = date(chunk_end.year + 1, 1, 1)
        result = merge_raw_segments(segments)
        result.attrs["provider"] = provider
        return result

    def index_history(self, symbol: str, start_date: date, end_date: date) -> pd.DataFrame:
        provider = "index_zh_a_hist"
        try:
            frame = self._call(
                provider,
                self.client.index_zh_a_hist,
                symbol=symbol,
                period="daily",
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
            )
        except RuntimeError:
            fallback = getattr(self.client, "stock_zh_index_daily", None)
            if not callable(fallback):
                raise
            provider = "stock_zh_index_daily"
            market_symbol = ("sh" if symbol.startswith("0") else "sz") + symbol
            frame = self._call(provider, fallback, symbol=market_symbol)
            frame = frame[
                (pd.to_datetime(frame["date"]).dt.date >= start_date)
                & (pd.to_datetime(frame["date"]).dt.date <= end_date)
            ].copy()
            if "amount" not in frame.columns and "成交额" not in frame.columns:
                frame["amount"] = 0.0
        result = self._normalize_history(frame)
        result.attrs["provider"] = provider
        return result

    def adjustment_factors(self, symbol: str) -> pd.DataFrame:
        market_symbol = infer_exchange(symbol) + symbol
        tables: dict[str, pd.DataFrame] = {}
        approximate = False
        for adjust, column in (("qfq-factor", "qfq_factor"), ("hfq-factor", "hfq_factor")):
            try:
                frame = self._call(
                    f"stock_zh_a_daily:{adjust}",
                    self.client.stock_zh_a_daily,
                    symbol=market_symbol,
                    adjust=adjust,
                ).copy()
                source_column = column if column in frame.columns else adjust.replace("-", "_")
                frame = frame.rename(columns={source_column: column})[["date", column]]
                frame["date"] = pd.to_datetime(frame["date"]).dt.date
                frame[column] = pd.to_numeric(frame[column], errors="raise")
            except (RuntimeError, KeyError, TypeError, ValueError):
                hist = getattr(self.client, "stock_zh_a_hist", None)
                if not callable(hist):
                    raise
                raw = self._call(
                    "stock_zh_a_hist:factor-fallback",
                    hist,
                    symbol=symbol,
                    period="daily",
                    adjust="",
                )
                dates = pd.to_datetime(raw["日期" if "日期" in raw.columns else "date"]).dt.date
                frame = pd.DataFrame({"date": dates, column: 1.0})
                approximate = True
            tables[column] = frame
        result = tables["qfq_factor"].merge(tables["hfq_factor"], on="date", how="outer")
        result = result.sort_values("date").ffill().bfill().reset_index(drop=True)
        result["factor_source"] = "stock_zh_a_daily_approx" if approximate else "stock_zh_a_daily"
        return result

    def sina_raw_history(
        self, exchange: str, code: str, start_date: date, end_date: date
    ) -> pd.DataFrame:
        kwargs = {
            "symbol": exchange.lower() + code,
            "start_date": start_date.strftime("%Y%m%d"),
            "end_date": end_date.strftime("%Y%m%d"),
            "adjust": "",
        }
        try:
            frame = self._call("stock_zh_a_daily:raw", self.client.stock_zh_a_daily, **kwargs)
            result = self._normalize_history(frame)
        except (RuntimeError, KeyError, TypeError, ValueError):
            # Sina's endpoint intermittently returns an empty/malformed payload
            # (notably a frame without ``date``). Retry the same raw request via
            # AkShare's EastMoney-backed history endpoint before failing the job.
            hist = getattr(self.client, "stock_zh_a_hist", None)
            if not callable(hist):
                raise
            frame = self._call(
                "stock_zh_a_hist:raw-fallback",
                hist,
                symbol=code,
                period="daily",
                start_date=kwargs["start_date"],
                end_date=kwargs["end_date"],
                adjust="",
            )
            result = self._normalize_history(frame)
        result.attrs["provider"] = "sina-akshare"
        return result

    def sina_adjustment_factors(self, exchange: str, code: str) -> pd.DataFrame:
        if exchange.lower() not in ("sh", "sz"):
            raise ValueError(f"unsupported Sina exchange: {exchange}")
        result = self.adjustment_factors(code)
        result.attrs["provider"] = "sina-akshare"
        return result

    def trading_calendar(self) -> list[date]:
        frame = self._call(
            "tool_trade_date_hist_sina", self.client.tool_trade_date_hist_sina
        )
        column = "trade_date" if "trade_date" in frame.columns else "交易日期"
        return sorted(pd.to_datetime(frame[column]).dt.date.drop_duplicates().tolist())

    @staticmethod
    def _normalize_history(frame: pd.DataFrame) -> pd.DataFrame:
        aliases = {
            "日期": "date", "date": "date", "开盘": "open", "open": "open",
            "最高": "high", "high": "high", "最低": "low", "low": "low",
            "收盘": "close", "close": "close", "成交量": "volume", "volume": "volume",
            "成交额": "amount", "amount": "amount",
        }
        normalized = frame.rename(columns={key: value for key, value in aliases.items() if key in frame.columns})
        required = ["date", "open", "high", "low", "close", "volume", "amount"]
        missing = [column for column in required if column not in normalized.columns]
        if missing:
            raise ValueError(f"AkShare response missing columns: {', '.join(missing)}")
        result = normalized[required].copy()
        result["date"] = pd.to_datetime(result["date"]).dt.date
        for column in required[1:]:
            result[column] = pd.to_numeric(result[column], errors="raise")
        return result.sort_values("date").drop_duplicates("date").reset_index(drop=True)

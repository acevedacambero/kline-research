from __future__ import annotations

from datetime import date
import time

import pandas as pd
import requests


class TencentHttpSource:
    """Fetch unadjusted daily bars from Tencent's K-line endpoint."""

    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"

    def __init__(
        self,
        session=None,
        retries: int = 3,
        timeout_seconds: float = 15,
        retry_delay: float = 0.25,
    ) -> None:
        if retries < 1:
            raise ValueError("retries must be at least 1")
        self.session = session or requests.Session()
        self.retries = retries
        self.timeout_seconds = timeout_seconds
        self.retry_delay = retry_delay

    def fetch_history(
        self, exchange: str, code: str, start_date: date, end_date: date
    ) -> pd.DataFrame:
        symbol = f"{exchange.lower()}{code}"
        return self._fetch_symbol(symbol, start_date, end_date)

    def index_history(
        self, exchange: str, start_date: date, end_date: date
    ) -> pd.DataFrame:
        symbols = {"sh": "sh000001", "sz": "sz399001"}
        try:
            symbol = symbols[exchange.lower()]
        except KeyError as exc:
            raise ValueError(f"unsupported index exchange: {exchange}") from exc
        result = self._fetch_symbol(symbol, start_date, end_date)
        result.attrs["provider"] = "tencent-http"
        return result

    def _fetch_symbol(
        self, symbol: str, start_date: date, end_date: date
    ) -> pd.DataFrame:
        params = {
            "param": (
                f"{symbol},day,{start_date.isoformat()},{end_date.isoformat()},90,"
            ),
        }
        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.get(
                    self.url, params=params, timeout=self.timeout_seconds
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or "code" not in payload:
                    raise ValueError("malformed Tencent response: provider code missing")
                if payload["code"] != 0:
                    message = payload.get("msg", payload.get("message", "unknown error"))
                    raise ValueError(
                        f"Tencent provider error code={payload['code']}: {message}"
                    )
                try:
                    instrument = payload["data"][symbol]
                except (KeyError, TypeError) as exc:
                    raise ValueError("malformed Tencent response: instrument missing") from exc
                if not isinstance(instrument, dict) or "day" not in instrument:
                    raise ValueError("malformed Tencent response: raw day series missing")
                rows = instrument["day"]
                if not rows:
                    raise ValueError("Tencent returned no daily rows")
                result = self._normalize(rows)
                result.attrs["provider"] = "tencent-http"
                return result
            except Exception as exc:
                if not self._is_retryable(exc) or attempt == self.retries:
                    raise RuntimeError(
                        f"Tencent {symbol} failed after {attempt} attempts: {exc}"
                    ) from exc
                if self.retry_delay:
                    time.sleep(self.retry_delay * attempt)
        raise AssertionError("unreachable")

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        if isinstance(exc, requests.HTTPError):
            status = exc.response.status_code if exc.response is not None else None
            return status == 429 or (status is not None and status >= 500)
        return isinstance(exc, (requests.Timeout, requests.ConnectionError))

    @staticmethod
    def _normalize(rows: object) -> pd.DataFrame:
        if not isinstance(rows, list) or any(
            not isinstance(row, (list, tuple)) or len(row) < 6 for row in rows
        ):
            raise ValueError("malformed Tencent daily rows")
        columns = ["date", "open", "close", "high", "low", "volume", "amount"]
        values = [list(row[:7]) + [None] * max(0, 7 - len(row)) for row in rows]
        result = pd.DataFrame(values, columns=columns)
        try:
            result["date"] = pd.to_datetime(result["date"], errors="raise").dt.date
            for column in columns[1:]:
                result[column] = pd.to_numeric(result[column], errors="raise")
        except Exception as exc:
            raise ValueError(f"malformed Tencent daily rows: {exc}") from exc
        return result.sort_values("date").drop_duplicates("date").reset_index(drop=True)

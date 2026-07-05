from __future__ import annotations

from datetime import date
import threading
import time

import pandas as pd
import requests


class EastMoneyHttpSource:
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
        "Referer": "https://quote.eastmoney.com/",
        "Accept": "application/json,text/plain,*/*",
        "Connection": "keep-alive",
    }

    def __init__(
        self,
        session=None,
        retries: int = 3,
        timeout_seconds: int = 15,
        retry_delay: float = 0.25,
    ):
        self._provided_session = session
        self._local = threading.local()
        self.retries = retries
        self.timeout_seconds = timeout_seconds
        self.retry_delay = retry_delay

    def _session(self):
        if self._provided_session is not None:
            return self._provided_session
        if not hasattr(self._local, "session"):
            self._local.session = requests.Session()
        return self._local.session

    @staticmethod
    def secid(exchange: str, code: str) -> str:
        return f'{1 if exchange.lower() == "sh" else 0}.{code}'

    def fetch_history(
        self,
        exchange: str,
        code: str,
        start_date: date,
        end_date: date,
        fqt: int = 0,
    ) -> pd.DataFrame:
        params = {
            "secid": self.secid(exchange, code),
            "klt": 101,
            "fqt": fqt,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "beg": start_date.strftime("%Y%m%d"),
            "end": end_date.strftime("%Y%m%d"),
        }
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                response = self._session().get(
                    self.url, params=params, timeout=self.timeout_seconds, headers=self.headers
                )
                response.raise_for_status()
                payload = response.json()
                rows = (payload.get("data") or {}).get("klines") or []
                return self._normalize(rows)
            except Exception as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(self.retry_delay * attempt)
        raise RuntimeError(
            f"EastMoney {exchange}{code} fqt={fqt} failed after {self.retries} attempts: {last_error}"
        ) from last_error

    @staticmethod
    def _normalize(rows: list[str]) -> pd.DataFrame:
        columns = ["date", "open", "close", "high", "low", "volume", "amount"]
        if not rows:
            return pd.DataFrame(columns=columns + ["provider", "fields_partial"])
        frame = pd.DataFrame([row.split(",")[:7] for row in rows], columns=columns)
        frame["date"] = pd.to_datetime(frame["date"]).dt.date
        for column in columns[1:]:
            frame[column] = pd.to_numeric(frame[column], errors="raise")
        frame["provider"] = "eastmoney-http"
        frame["fields_partial"] = False
        return frame.sort_values("date").drop_duplicates("date").reset_index(drop=True)

    def fetch_bundle(
        self, exchange: str, code: str, start_date: date, end_date: date
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        raw = self.fetch_history(exchange, code, start_date, end_date, 0)
        qfq = self.fetch_history(exchange, code, start_date, end_date, 1)
        hfq = self.fetch_history(exchange, code, start_date, end_date, 2)
        if raw.empty:
            raise ValueError(f"EastMoney returned no raw history for {exchange}{code}")
        factors = raw[["date", "close"]].rename(columns={"close": "close_raw"})
        factors = factors.merge(
            qfq[["date", "close"]].rename(columns={"close": "close_qfq"}), on="date"
        ).merge(
            hfq[["date", "close"]].rename(columns={"close": "close_hfq"}), on="date"
        )
        valid = (factors["close_raw"] != 0) & (factors["close_qfq"] != 0)
        factors = factors.loc[valid].copy()
        factors["qfq_factor"] = factors["close_raw"] / factors["close_qfq"]
        factors["hfq_factor"] = factors["close_hfq"] / factors["close_raw"]
        factors["factor_source"] = "eastmoney-http-same-source"
        return raw, factors[["date", "qfq_factor", "hfq_factor", "factor_source"]]

from __future__ import annotations

from datetime import date
import threading


class HybridDownloadSource:
    def __init__(self, direct, fallback):
        self.direct = direct
        self.fallback = fallback
        self.direct_available = True
        self._lock = threading.Lock()
        self.direct_error: str | None = None

    def fetch_bundle(self, exchange: str, code: str, start: date, end: date):
        if self.direct_available:
            try:
                return self.direct.fetch_bundle(exchange, code, start, end)
            except Exception as exc:
                with self._lock:
                    self.direct_available = False
                    self.direct_error = str(exc)
        raw = self.fallback.stock_history(code, start, end, "")
        factors = self.fallback.adjustment_factors(code)
        return raw, factors

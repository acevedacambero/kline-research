from datetime import date

import pandas as pd

from kline.data.download_source import HybridDownloadSource


class FastFails:
    calls = 0

    def fetch_bundle(self, *args):
        self.calls += 1
        raise ConnectionError("blocked")


class FallbackWorks:
    calls = 0

    def stock_history(self, *args):
        self.calls += 1
        return pd.DataFrame([{"date": date(2024, 1, 1), "close": 10.0}])

    def adjustment_factors(self, code):
        return pd.DataFrame([{"date": date(1900, 1, 1), "qfq_factor": 1.0, "hfq_factor": 1.0}])


def test_hybrid_source_opens_circuit_after_direct_provider_failure():
    fast, fallback = FastFails(), FallbackWorks()
    source = HybridDownloadSource(fast, fallback)
    source.fetch_bundle("sh", "600000", date(2024, 1, 1), date(2024, 1, 2))
    source.fetch_bundle("sz", "000001", date(2024, 1, 1), date(2024, 1, 2))
    assert fast.calls == 1
    assert fallback.calls == 2
    assert source.direct_available is False

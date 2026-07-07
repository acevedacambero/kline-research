from datetime import date

import pandas as pd
import pytest

from kline.data.provider_policy import (
    HISTORY_BACKFILL_VERSION,
    MarketNotSupportedError,
    ProductionProviderPolicy,
)


def bars():
    return pd.DataFrame(
        [{"date": date(2024, 1, 2), "open": 10, "high": 11, "low": 9,
          "close": 10.5, "volume": 100, "amount": 1000}]
    )


def factors():
    return pd.DataFrame(
        [{"date": date(2024, 1, 2), "qfq_factor": 1.0,
          "hfq_factor": 1.0, "factor_source": "stock_zh_a_daily"}]
    )


class TencentFake:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def fetch_history(self, exchange, code, start, end):
        self.calls.append((exchange, code, start, end))
        if self.error:
            raise self.error
        return bars()


class SinaFake:
    def __init__(self):
        self.raw_calls = []
        self.factor_calls = []

    def sina_raw_history(self, exchange, code, start, end):
        self.raw_calls.append((exchange, code, start, end))
        return bars()

    def sina_adjustment_factors(self, exchange, code):
        self.factor_calls.append((exchange, code))
        return factors()


@pytest.mark.parametrize(("exchange", "code"), [("sh", "600000"), ("sz", "000001")])
def test_routes_raw_to_tencent_and_factors_to_sina(exchange, code):
    tencent, sina = TencentFake(), SinaFake()
    policy = ProductionProviderPolicy(tencent=tencent, sina=sina)

    raw, factor_frame = policy.fetch_bundle(
        exchange, code, date(2024, 1, 1), date(2024, 1, 3)
    )

    assert len(tencent.calls) == 1
    assert not sina.raw_calls
    assert sina.factor_calls == [(exchange, code)]
    assert raw.attrs["provider"] == "tencent-http"
    assert factor_frame.attrs["provider"] == "sina-akshare"


def test_tencent_failure_uses_explicit_sina_raw_fallback():
    tencent, sina = TencentFake(RuntimeError("down")), SinaFake()
    policy = ProductionProviderPolicy(tencent=tencent, sina=sina)

    raw, _ = policy.fetch_bundle(
        "sh", "600000", date(2024, 1, 1), date(2024, 1, 3)
    )

    assert len(tencent.calls) == 1
    assert len(sina.raw_calls) == 1
    assert raw.attrs["provider"] == "sina-akshare"


def test_long_history_bundle_bypasses_tencent():
    tencent, sina = TencentFake(), SinaFake()
    policy = ProductionProviderPolicy(tencent=tencent, sina=sina)

    raw, factor_frame = policy.fetch_long_history_bundle(
        "sh", "600000", date(1990, 1, 1), date(2026, 7, 7)
    )

    assert tencent.calls == []
    assert sina.raw_calls == [("sh", "600000", date(1990, 1, 1), date(2026, 7, 7))]
    assert sina.factor_calls == [("sh", "600000")]
    assert raw.attrs == {
        "provider": "sina-akshare",
        "provider_policy_version": HISTORY_BACKFILL_VERSION,
    }
    assert factor_frame.attrs["provider_policy_version"] == HISTORY_BACKFILL_VERSION


def test_rejects_beijing_before_calling_any_provider():
    tencent, sina = TencentFake(), SinaFake()
    policy = ProductionProviderPolicy(tencent=tencent, sina=sina)

    with pytest.raises(MarketNotSupportedError, match="bj"):
        policy.fetch_bundle("bj", "920001", date(2024, 1, 1), date(2024, 1, 3))

    assert not tencent.calls
    assert not sina.raw_calls
    assert not sina.factor_calls


@pytest.mark.parametrize(
    "invalid_factors",
    [pd.DataFrame(), pd.DataFrame([{"date": date(2024, 1, 2), "qfq_factor": None}])],
)
def test_rejects_incomplete_factor_data(invalid_factors):
    sina = SinaFake()
    sina.sina_adjustment_factors = lambda exchange, code: invalid_factors

    with pytest.raises(ValueError, match="factor"):
        ProductionProviderPolicy(TencentFake(), sina).fetch_bundle(
            "sz", "000001", date(2024, 1, 1), date(2024, 1, 3)
        )

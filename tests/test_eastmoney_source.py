from datetime import date

import pytest

from kline.data.eastmoney_source import EastMoneyHttpSource


class FakeResponse:
    def __init__(self, rows):
        self.rows = rows

    def raise_for_status(self):
        return None

    def json(self):
        return {"data": {"klines": self.rows}}


class FakeSession:
    def __init__(self):
        self.calls = []

    def get(self, url, params, timeout, headers):
        self.calls.append((url, params, timeout, headers))
        factor = {0: 1.0, 1: 0.5, 2: 2.0}[params["fqt"]]
        return FakeResponse([
            f"2024-01-02,{10*factor},{10.5*factor},{11*factor},{9.5*factor},1000,2000"
        ])


def test_fetch_history_uses_correct_secid_and_normalizes_kline_fields():
    session = FakeSession()
    source = EastMoneyHttpSource(session=session)
    frame = source.fetch_history("sh", "600000", date(2024, 1, 1), date(2024, 1, 3), 0)
    assert session.calls[0][1]["secid"] == "1.600000"
    assert "Mozilla" in session.calls[0][3]["User-Agent"]
    assert frame.iloc[0].to_dict() == {
        "date": date(2024, 1, 2), "open": 10.0, "close": 10.5, "high": 11.0,
        "low": 9.5, "volume": 1000.0, "amount": 2000.0,
        "provider": "eastmoney-http", "fields_partial": False,
    }


def test_fetch_bundle_keeps_raw_as_fact_and_derives_factors_from_same_provider():
    raw, factors = EastMoneyHttpSource(session=FakeSession()).fetch_bundle(
        "sz", "000001", date(2024, 1, 1), date(2024, 1, 3)
    )
    assert raw.iloc[0]["close"] == 10.5
    assert factors.iloc[0]["qfq_factor"] == pytest.approx(2.0)
    assert factors.iloc[0]["hfq_factor"] == pytest.approx(2.0)
    assert factors.iloc[0]["factor_source"] == "eastmoney-http-same-source"

from datetime import date

import pandas as pd
import pytest

from kline.data.akshare_source import AkShareSource


class FakeAkShare:
    def stock_info_a_code_name(self):
        return pd.DataFrame([{"code": "600000", "name": "浦发银行"}, {"code": "000001", "name": "平安银行"}, {"code": "920001", "name": "纬达光电"}])

    def stock_zh_a_hist(self, **kwargs):
        return pd.DataFrame([{
            "日期": "2024-01-02", "股票代码": kwargs["symbol"], "开盘": 10.0,
            "收盘": 10.5, "最高": 11.0, "最低": 9.8, "成交量": 1234, "成交额": 5678.0,
        }])

    def stock_zh_a_daily(self, **kwargs):
        return pd.DataFrame([{
            "date": "2024-01-02", "open": 10.0, "close": 10.5, "high": 11.0,
            "low": 9.8, "volume": 1234, "amount": 5678.0,
        }])

    def index_zh_a_hist(self, **kwargs):
        return pd.DataFrame([{
            "日期": "2024-01-02", "开盘": 3000.0, "收盘": 3010.0,
            "最高": 3020.0, "最低": 2990.0, "成交量": 100, "成交额": 200.0,
        }])

    def stock_zh_index_daily(self, **kwargs):
        return pd.DataFrame([{
            "date": "2024-01-02", "open": 3000.0, "close": 3010.0,
            "high": 3020.0, "low": 2990.0, "volume": 100,
        }])

    def tool_trade_date_hist_sina(self):
        return pd.DataFrame([{"trade_date": "2024-01-02"}, {"trade_date": "2024-01-03"}])


def test_security_list_normalizes_exchange_and_name():
    rows = AkShareSource(FakeAkShare()).list_securities()
    assert rows == [
        {"exchange": "sh", "code": "600000", "name": "浦发银行"},
        {"exchange": "sz", "code": "000001", "name": "平安银行"},
        {"exchange": "bj", "code": "920001", "name": "纬达光电"},
    ]


def test_stock_history_normalizes_chinese_columns_and_adjust_mode():
    frame = AkShareSource(FakeAkShare()).stock_history("600000", date(2024, 1, 1), date(2024, 1, 3), "qfq")
    assert frame.iloc[0].to_dict() == {
        "date": date(2024, 1, 2), "open": 10.0, "high": 11.0, "low": 9.8,
        "close": 10.5, "volume": 1234, "amount": 5678.0,
        "fields_partial": False, "provider": "eastmoney", "provider_priority": 0,
    }


def test_index_history_uses_same_internal_contract():
    frame = AkShareSource(FakeAkShare()).index_history("000001", date(2024, 1, 1), date(2024, 1, 3))
    assert list(frame.columns) == ["date", "open", "high", "low", "close", "volume", "amount"]
    assert frame.iloc[0]["date"] == date(2024, 1, 2)


def test_index_history_retries_transient_upstream_disconnect():
    client = FakeAkShare()
    original = client.index_zh_a_hist
    attempts = 0

    def flaky(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ConnectionError("remote disconnected")
        return original(**kwargs)

    client.index_zh_a_hist = flaky
    frame = AkShareSource(client, retries=3, retry_delay=0).index_history(
        "000001", date(2024, 1, 1), date(2024, 1, 3)
    )
    assert len(frame) == 1
    assert attempts == 3


def test_history_raises_contextual_error_after_retry_budget():
    client = FakeAkShare()
    client.index_zh_a_hist = lambda **kwargs: (_ for _ in ()).throw(ConnectionError("down"))
    client.stock_zh_index_daily = None
    with pytest.raises(RuntimeError, match="index_zh_a_hist failed after 2 attempts"):
        AkShareSource(client, retries=2, retry_delay=0).index_history(
            "000001", date(2024, 1, 1), date(2024, 1, 3)
        )


def test_sina_raw_history_falls_back_when_daily_payload_has_no_date():
    client = FakeAkShare()
    client.stock_zh_a_daily = lambda **kwargs: pd.DataFrame()
    frame = AkShareSource(client, retries=1, retry_delay=0).sina_raw_history(
        "sh", "600000", date(2024, 1, 1), date(2024, 1, 3)
    )
    assert len(frame) == 1
    assert frame.attrs["provider"] == "sina-akshare"


def test_index_history_falls_back_to_sina_provider():
    client = FakeAkShare()
    client.index_zh_a_hist = lambda **kwargs: (_ for _ in ()).throw(ConnectionError("down"))
    frame = AkShareSource(client, retries=1, retry_delay=0).index_history(
        "000001", date(2024, 1, 1), date(2024, 1, 3)
    )
    assert len(frame) == 1
    assert frame.attrs["provider"] == "stock_zh_index_daily"
    assert frame.iloc[0]["amount"] == 0.0


def test_stock_history_splits_long_ranges_into_bounded_requests():
    client = FakeAkShare()
    ranges = []
    original = client.stock_zh_a_hist

    def bounded(**kwargs):
        ranges.append((kwargs["start_date"], kwargs["end_date"]))
        return original(**kwargs)

    client.stock_zh_a_hist = bounded
    AkShareSource(client, chunk_years=1).stock_history(
        "600000", date(2020, 1, 1), date(2022, 1, 2), "qfq"
    )
    assert len(ranges) == 3
    assert ranges[0] == ("20200101", "20201231")


def test_stock_history_falls_back_to_sina_daily_provider():
    client = FakeAkShare()
    client.stock_zh_a_hist = lambda **kwargs: (_ for _ in ()).throw(ConnectionError("down"))
    frame = AkShareSource(client, retries=1).stock_history(
        "600000", date(2024, 1, 1), date(2024, 1, 3), "qfq"
    )
    assert len(frame) == 1
    assert frame.attrs["provider"] == "stock_zh_a_daily"


def test_adjustment_factors_normalize_qfq_and_hfq_tables():
    client = FakeAkShare()

    def daily(**kwargs):
        column = kwargs["adjust"].replace("-", "_")
        return pd.DataFrame([{"date": "2024-01-02", column: "1.25"}])

    client.stock_zh_a_daily = daily
    factors = AkShareSource(client).adjustment_factors("600000")
    assert factors.iloc[0].to_dict() == {
        "date": date(2024, 1, 2), "qfq_factor": 1.25, "hfq_factor": 1.25,
        "factor_source": "stock_zh_a_daily",
    }


def test_trading_calendar_uses_dedicated_calendar_provider():
    dates = AkShareSource(FakeAkShare()).trading_calendar()
    assert dates == [date(2024, 1, 2), date(2024, 1, 3)]

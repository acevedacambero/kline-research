from datetime import date

import pytest
import requests

from kline.data.tencent_source import TencentHttpSource
from kline.ops.provider_probe import classify_error


class Response:
    def __init__(self, payload=None, http_error=None):
        self.payload = payload
        self.http_error = http_error

    def raise_for_status(self):
        if self.http_error is not None:
            raise self.http_error

    def json(self):
        return self.payload


class Session:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, Response):
            return outcome
        return Response(outcome)


def payload(rows):
    return {"code": 0, "msg": "", "data": {"sh600000": {"day": rows}}}


def symbol_payload(symbol, rows):
    return {"code": 0, "msg": "", "data": {symbol: {"day": rows}}}


def test_normalizes_raw_daily_rows_without_adjusted_series_mixing():
    session = Session([payload([["2026-07-01", "10", "11", "12", "9", "100", "1000"]])])

    frame = TencentHttpSource(session=session).fetch_history(
        "sh", "600000", date(2026, 4, 1), date(2026, 7, 1)
    )

    assert list(frame.columns) == ["date", "open", "close", "high", "low", "volume", "amount"]
    assert frame.iloc[0].to_dict() == {
        "date": date(2026, 7, 1), "open": 10, "close": 11, "high": 12,
        "low": 9, "volume": 100, "amount": 1000,
    }


def test_uses_raw_daily_query_parameters_and_bounded_timeout():
    session = Session([payload([["2026-07-01", "10", "11", "12", "9", "100"]])])

    TencentHttpSource(session=session, timeout_seconds=7).fetch_history(
        "sh", "600000", date(2026, 4, 1), date(2026, 7, 1)
    )

    url, kwargs = session.calls[0]
    assert url == "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    assert kwargs["timeout"] == 7
    assert kwargs["params"] == {
        "param": "sh600000,day,2026-04-01,2026-07-01,90,",
    }
    assert not any(
        token in str(kwargs["params"]).lower() for token in ("qfq", "hfq")
    )


def test_retries_transient_failure_then_returns_rows():
    session = Session([
        requests.Timeout("late"),
        payload([["2026-07-01", "10", "11", "12", "9", "100"]]),
    ])

    frame = TencentHttpSource(session=session, retries=2, retry_delay=0).fetch_history(
        "sh", "600000", date(2026, 4, 1), date(2026, 7, 1)
    )

    assert len(session.calls) == 2
    assert len(frame) == 1


def test_reports_provider_error_before_looking_for_raw_series():
    response = {"code": 1, "msg": "bad params", "data": {}}
    session = Session([response])

    with pytest.raises(RuntimeError, match="Tencent provider error.*bad params") as error:
        TencentHttpSource(session=session, retry_delay=0).fetch_history(
            "sh", "600000", date(2026, 4, 1), date(2026, 7, 1)
        )

    assert len(session.calls) == 1
    assert classify_error(error.value) == "data"


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (payload([]), "no daily rows"),
        ({"data": {"sh600000": {"day": [["bad"]]}}}, "malformed"),
        ({"unexpected": True}, "malformed"),
    ],
)
def test_rejects_empty_or_malformed_responses(response, message):
    session = Session([response])

    with pytest.raises(RuntimeError, match=message) as error:
        TencentHttpSource(session=session, retry_delay=0).fetch_history(
            "sh", "600000", date(2026, 4, 1), date(2026, 7, 1)
        )

    assert len(session.calls) == 1
    assert classify_error(error.value) == "data"


def test_does_not_retry_nonretryable_http_status():
    response = requests.Response()
    response.status_code = 404
    http_error = requests.HTTPError("not found", response=response)
    session = Session([Response(http_error=http_error)])

    with pytest.raises(RuntimeError, match="not found"):
        TencentHttpSource(session=session, retry_delay=0).fetch_history(
            "sh", "600000", date(2026, 4, 1), date(2026, 7, 1)
        )

    assert len(session.calls) == 1


@pytest.mark.parametrize("status_code", [429, 503])
def test_retries_retryable_http_status_then_returns_rows(status_code):
    response = requests.Response()
    response.status_code = status_code
    http_error = requests.HTTPError("retryable", response=response)
    session = Session([
        Response(http_error=http_error),
        payload([["2026-07-01", "10", "11", "12", "9", "100"]]),
    ])

    frame = TencentHttpSource(session=session, retries=2, retry_delay=0).fetch_history(
        "sh", "600000", date(2026, 4, 1), date(2026, 7, 1)
    )

    assert len(session.calls) == 2
    assert len(frame) == 1


@pytest.mark.parametrize(
    ("exchange", "symbol"), [("sh", "sh000001"), ("sz", "sz399001")]
)
def test_index_history_uses_explicit_tencent_market_mapping(exchange, symbol):
    session = Session([
        symbol_payload(symbol, [["2026-07-01", "3000", "3010", "3020", "2990", "100"]])
    ])

    frame = TencentHttpSource(session=session).index_history(
        exchange, date(2026, 7, 1), date(2026, 7, 2)
    )

    assert frame.iloc[0]["close"] == 3010
    assert frame.attrs["provider"] == "tencent-http"
    assert session.calls[0][1]["params"]["param"].startswith(symbol + ",day,")


@pytest.mark.parametrize("exchange", ["bj", "hk", ""])
def test_index_history_rejects_unsupported_exchange(exchange):
    source = TencentHttpSource(session=Session([]))

    with pytest.raises(ValueError, match="index exchange"):
        source.index_history(exchange, date(2026, 7, 1), date(2026, 7, 2))

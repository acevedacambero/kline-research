from datetime import date

import pytest

from kline.data.tencent_source import TencentHttpSource
from kline.ops.provider_probe import classify_error


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

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
        return Response(outcome)


def payload(rows):
    return {"code": 0, "msg": "", "data": {"sh600000": {"day": rows}}}


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
        TimeoutError("late"),
        payload([["2026-07-01", "10", "11", "12", "9", "100"]]),
    ])

    frame = TencentHttpSource(session=session, retries=2, retry_delay=0).fetch_history(
        "sh", "600000", date(2026, 4, 1), date(2026, 7, 1)
    )

    assert len(session.calls) == 2
    assert len(frame) == 1


def test_reports_provider_error_before_looking_for_raw_series():
    response = {"code": 1, "msg": "bad params", "data": {}}

    with pytest.raises(RuntimeError, match="Tencent provider error.*bad params") as error:
        TencentHttpSource(session=Session([response]), retries=1).fetch_history(
            "sh", "600000", date(2026, 4, 1), date(2026, 7, 1)
        )

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
    with pytest.raises(RuntimeError, match=message):
        TencentHttpSource(session=Session([response]), retries=1).fetch_history(
            "sh", "600000", date(2026, 4, 1), date(2026, 7, 1)
        )

from dataclasses import FrozenInstanceError

import pytest

from kline.ops.provider_probe import (
    CALENDAR_PROVIDER,
    EASTMONEY_PROVIDER,
    INDEX_PROVIDER,
    SINA_PROVIDER,
    TENCENT_PROVIDER,
    ProbeObservation,
    classify_error,
    evaluate_gate,
    percentile,
)


REQUIRED_FIELDS = ("open", "high", "low", "close", "volume")


def observation(
    provider: str,
    *,
    security: str = "stock",
    success: bool = True,
    elapsed_seconds: float = 0.1,
    rows: int = 10,
    missing_fields: tuple[str, ...] = (),
    error_type: str | None = None,
) -> ProbeObservation:
    return ProbeObservation(
        provider=provider,
        security=security,
        success=success,
        elapsed_seconds=elapsed_seconds,
        rows=rows,
        missing_fields=missing_fields,
        error_type=error_type,
    )


def passing_observations() -> list[ProbeObservation]:
    return [
        *(observation(EASTMONEY_PROVIDER) for _ in range(9)),
        observation(EASTMONEY_PROVIDER, success=False, rows=0, error_type="timeout"),
        *(observation(TENCENT_PROVIDER) for _ in range(4)),
        observation(TENCENT_PROVIDER, success=False, rows=0, error_type="network"),
        observation(SINA_PROVIDER),
        observation(INDEX_PROVIDER, security="index"),
        observation(CALENDAR_PROVIDER, security="calendar"),
    ]


def test_probe_models_are_immutable() -> None:
    item = observation(EASTMONEY_PROVIDER)
    report = evaluate_gate(passing_observations())

    with pytest.raises(FrozenInstanceError):
        item.success = False  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        report.passed = False  # type: ignore[misc]


def test_passing_gate_aggregates_rates_latency_counts_and_errors() -> None:
    items = passing_observations()
    items[0] = observation(EASTMONEY_PROVIDER, elapsed_seconds=1.0)
    items[1] = observation(EASTMONEY_PROVIDER, elapsed_seconds=2.0)
    report = evaluate_gate(items)

    eastmoney = report.providers[EASTMONEY_PROVIDER]
    assert report.passed is True
    assert report.reasons == ()
    assert eastmoney.success_rate == pytest.approx(0.9)
    assert eastmoney.mean_latency_seconds == pytest.approx(0.38)
    assert eastmoney.p95_latency_seconds == pytest.approx(1.55)
    assert eastmoney.empty_response_count == 1
    assert eastmoney.missing_field_count == 0
    assert eastmoney.error_categories == {"timeout": 1}


def test_gate_lists_each_threshold_failure() -> None:
    items = [
        observation(EASTMONEY_PROVIDER),
        observation(EASTMONEY_PROVIDER, success=False, rows=0, error_type="timeout"),
        observation(TENCENT_PROVIDER, success=False, rows=0, error_type="network"),
        observation(SINA_PROVIDER, success=False, rows=0, error_type="http"),
        observation(INDEX_PROVIDER, security="index", success=False, rows=0),
        observation(CALENDAR_PROVIDER, security="calendar", success=False, rows=0),
    ]

    report = evaluate_gate(items)

    assert report.passed is False
    assert any("EastMoney success rate" in reason for reason in report.reasons)
    assert any("Tencent success rate" in reason for reason in report.reasons)
    assert any("Sina" in reason for reason in report.reasons)
    assert any("index" in reason for reason in report.reasons)
    assert any("calendar" in reason for reason in report.reasons)


def test_empty_input_fails_without_crashing_and_has_provider_summaries() -> None:
    report = evaluate_gate([])

    assert report.passed is False
    assert set(report.providers) == {
        EASTMONEY_PROVIDER,
        TENCENT_PROVIDER,
        SINA_PROVIDER,
        INDEX_PROVIDER,
        CALENDAR_PROVIDER,
    }
    assert report.providers[EASTMONEY_PROVIDER].success_rate == 0.0
    assert report.providers[EASTMONEY_PROVIDER].mean_latency_seconds == 0.0
    assert any("No probe observations" in reason for reason in report.reasons)


def test_empty_success_and_missing_ohlcv_fail_explicitly() -> None:
    items = passing_observations()
    items[0] = observation(EASTMONEY_PROVIDER, rows=0)
    items[-2] = observation(
        INDEX_PROVIDER,
        security="index",
        missing_fields=("volume",),
    )

    report = evaluate_gate(items)

    assert report.passed is False
    assert report.providers[EASTMONEY_PROVIDER].empty_response_count == 2
    assert report.providers[INDEX_PROVIDER].missing_field_count == 1
    assert any("empty response" in reason for reason in report.reasons)
    assert any("missing required OHLCV fields" in reason for reason in report.reasons)


@pytest.mark.parametrize(
    ("provider", "security", "missing_field"),
    [
        (EASTMONEY_PROVIDER, "600000", "open"),
        (TENCENT_PROVIDER, "300750", "high"),
        (SINA_PROVIDER, "600519", "close"),
        (INDEX_PROVIDER, "000001", "volume"),
    ],
)
def test_market_provider_requires_ohlcv_for_real_security_identifiers(
    provider: str,
    security: str,
    missing_field: str,
) -> None:
    items = passing_observations()
    target = next(index for index, item in enumerate(items) if item.provider == provider)
    items[target] = observation(
        provider,
        security=security,
        missing_fields=(missing_field,),
    )

    report = evaluate_gate(items)

    assert report.passed is False
    assert any("missing required OHLCV fields" in reason for reason in report.reasons)


@pytest.mark.parametrize(
    ("missing_provider", "expected_reason"),
    [
        (EASTMONEY_PROVIDER, "No EastMoney observations"),
        (TENCENT_PROVIDER, "No Tencent observations"),
    ],
)
def test_missing_threshold_provider_has_explicit_no_observations_reason(
    missing_provider: str,
    expected_reason: str,
) -> None:
    items = [item for item in passing_observations() if item.provider != missing_provider]

    report = evaluate_gate(items)

    assert report.passed is False
    assert any(expected_reason in reason for reason in report.reasons)


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (TimeoutError("late"), "timeout"),
        (ConnectionError("offline"), "network"),
        (ValueError("bad payload"), "data"),
        (RuntimeError("boom"), "runtime"),
    ],
)
def test_classify_error_uses_stable_categories(error: Exception, category: str) -> None:
    assert classify_error(error) == category


def test_percentile_uses_linear_interpolation_and_handles_empty_values() -> None:
    assert percentile([], 95) == 0.0
    assert percentile([4.0], 95) == 4.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 50) == pytest.approx(2.5)
    assert percentile([1.0, 2.0], 95) == pytest.approx(1.95)


def test_canonical_provider_names_are_stable() -> None:
    assert (EASTMONEY_PROVIDER, TENCENT_PROVIDER, SINA_PROVIDER) == (
        "eastmoney",
        "tencent",
        "sina",
    )
    assert (INDEX_PROVIDER, CALENDAR_PROVIDER) == ("index", "calendar")
    assert REQUIRED_FIELDS == ("open", "high", "low", "close", "volume")

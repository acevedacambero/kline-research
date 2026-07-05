import json
from dataclasses import FrozenInstanceError

import pytest
import requests

from kline.ops.provider_probe import (
    CALENDAR_PROVIDER,
    EASTMONEY_PROVIDER,
    INDEX_PROVIDER,
    SINA_PROVIDER,
    TENCENT_PROVIDER,
    ProbeObservation,
    ProviderProbeRunner,
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
    assert eastmoney.empty_response_count == 0
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
    assert report.providers[EASTMONEY_PROVIDER].empty_response_count == 1
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
        (requests.ConnectionError("offline"), "network"),
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


@pytest.mark.parametrize("values", [[], [1.0]])
@pytest.mark.parametrize("percent", [-0.1, 100.1])
def test_percentile_rejects_invalid_percent_for_all_inputs(
    values: list[float], percent: float
) -> None:
    with pytest.raises(ValueError, match="between 0 and 100"):
        percentile(values, percent)


def test_transport_failure_is_not_an_empty_response() -> None:
    report = evaluate_gate(
        [observation(EASTMONEY_PROVIDER, success=False, rows=0, error_type="timeout")]
    )

    assert report.providers[EASTMONEY_PROVIDER].empty_response_count == 0


def test_observation_normalizes_missing_fields_and_report_is_deeply_immutable() -> None:
    item = observation(EASTMONEY_PROVIDER)
    item = ProbeObservation(
        provider=item.provider,
        security=item.security,
        success=item.success,
        elapsed_seconds=item.elapsed_seconds,
        rows=item.rows,
        missing_fields=["open", "volume"],  # type: ignore[arg-type]
    )
    report = evaluate_gate(passing_observations())

    assert item.missing_fields == ("open", "volume")
    with pytest.raises(TypeError):
        report.providers[EASTMONEY_PROVIDER] = report.providers[EASTMONEY_PROVIDER]  # type: ignore[index]
    with pytest.raises(TypeError):
        report.providers[EASTMONEY_PROVIDER].error_categories["timeout"] = 1  # type: ignore[index]
    assert isinstance(report.reasons, tuple)


def test_report_to_dict_is_json_serializable_and_detached() -> None:
    report = evaluate_gate(passing_observations())

    payload = report.to_dict()

    assert json.loads(json.dumps(payload))["passed"] is True
    assert isinstance(payload["reasons"], list)
    assert payload["observations"][0] == {
        "provider": "eastmoney",
        "security": "stock",
        "success": True,
        "elapsed_seconds": 0.1,
        "rows": 10,
        "missing_fields": [],
        "error_type": None,
        "error_message": None,
    }
    assert isinstance(payload["providers"][EASTMONEY_PROVIDER]["error_categories"], dict)
    payload["providers"][EASTMONEY_PROVIDER]["success_rate"] = 0.0
    assert report.providers[EASTMONEY_PROVIDER].success_rate == pytest.approx(0.9)
    assert report.observations == tuple(passing_observations())
    with pytest.raises(FrozenInstanceError):
        report.observations[0].rows = 0  # type: ignore[misc]


def test_tencent_exactly_eighty_percent_passes() -> None:
    report = evaluate_gate(passing_observations())

    assert report.providers[TENCENT_PROVIDER].success_rate == pytest.approx(0.8)
    assert not any("Tencent success rate" in reason for reason in report.reasons)
    assert report.passed is True


def test_tencent_just_below_eighty_percent_fails_with_explicit_reason() -> None:
    items = passing_observations()
    removed = False
    below_boundary = []
    for item in items:
        if item.provider == TENCENT_PROVIDER and item.success and not removed:
            removed = True
            continue
        below_boundary.append(item)

    report = evaluate_gate(below_boundary)

    assert report.providers[TENCENT_PROVIDER].success_rate == pytest.approx(0.75)
    assert any(
        reason == "Tencent success rate 75.0% is below 80%." for reason in report.reasons
    )
    assert report.passed is False


def test_canonical_provider_names_are_stable() -> None:
    assert (EASTMONEY_PROVIDER, TENCENT_PROVIDER, SINA_PROVIDER) == (
        "eastmoney",
        "tencent",
        "sina",
    )
    assert (INDEX_PROVIDER, CALENDAR_PROVIDER) == ("index", "calendar")
    assert REQUIRED_FIELDS == ("open", "high", "low", "close", "volume")


class FrameLike:
    columns = REQUIRED_FIELDS

    def __len__(self):
        return 5


def test_full_runner_executes_exact_provider_counts_and_serializes() -> None:
    calls = []

    def adapter(exchange, code, start_date, end_date):
        calls.append((exchange, code, start_date, end_date))
        assert (end_date - start_date).days == 90
        return FrameLike()

    runner = ProviderProbeRunner(
        adapters={provider: adapter for provider in (
            EASTMONEY_PROVIDER, TENCENT_PROVIDER, SINA_PROVIDER,
            INDEX_PROVIDER, CALENDAR_PROVIDER,
        )}
    )

    report = runner.run()

    assert {name: summary.observations for name, summary in report.providers.items()} == {
        EASTMONEY_PROVIDER: 10,
        TENCENT_PROVIDER: 10,
        SINA_PROVIDER: 3,
        INDEX_PROVIDER: 1,
        CALENDAR_PROVIDER: 1,
    }
    assert len(calls) == 25
    json.dumps(report.to_dict())


def test_runner_records_failures_and_missing_fields_without_aborting() -> None:
    attempts = 0

    class MissingFrame:
        columns = ("open", "close")

        def __len__(self):
            return 2

    def adapter(*args):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("late")
        return MissingFrame()

    runner = ProviderProbeRunner(adapters={provider: adapter for provider in (
        EASTMONEY_PROVIDER, TENCENT_PROVIDER, SINA_PROVIDER,
        INDEX_PROVIDER, CALENDAR_PROVIDER,
    )})

    report = runner.run()

    assert attempts == 25
    assert report.providers[EASTMONEY_PROVIDER].error_categories == {"timeout": 1}
    assert report.providers[EASTMONEY_PROVIDER].missing_field_count > 0
    assert report.passed is False
    assert len(report.to_dict()["observations"]) == 25


@pytest.mark.parametrize(
    ("error", "category"),
    [(TimeoutError("late"), "timeout"), (ConnectionError("offline"), "network")],
)
def test_runner_preserves_wrapped_transport_error_category(error, category) -> None:
    def adapter(*args):
        try:
            raise error
        except Exception as exc:
            raise RuntimeError("provider attempts exhausted") from exc

    adapters = {provider: lambda *args: FrameLike() for provider in (
        EASTMONEY_PROVIDER, TENCENT_PROVIDER, SINA_PROVIDER,
        INDEX_PROVIDER, CALENDAR_PROVIDER,
    )}
    adapters[TENCENT_PROVIDER] = adapter

    report = ProviderProbeRunner(adapters=adapters).run(quick=True)

    tencent = [item for item in report.observations if item.provider == TENCENT_PROVIDER]
    assert all(item.error_type == category for item in tencent)


def test_explicit_default_index_adapter_never_calls_fallback() -> None:
    class FakeClient:
        fallback_called = False

        def index_zh_a_hist(self, **kwargs):
            raise ConnectionError("primary unavailable")

        def stock_zh_index_daily(self, **kwargs):
            self.fallback_called = True
            return FrameLike()

    client = FakeClient()
    adapters = {provider: lambda *args: FrameLike() for provider in (
        EASTMONEY_PROVIDER, TENCENT_PROVIDER, SINA_PROVIDER,
        INDEX_PROVIDER, CALENDAR_PROVIDER,
    )}
    adapters[INDEX_PROVIDER] = ProviderProbeRunner.index_adapter(client)

    report = ProviderProbeRunner(adapters=adapters).run(quick=True)

    item = next(item for item in report.observations if item.provider == INDEX_PROVIDER)
    assert item.success is False
    assert item.error_type == "network"
    assert client.fallback_called is False


def test_quick_runner_is_explicitly_diagnostic_and_never_passes_gate() -> None:
    runner = ProviderProbeRunner(adapters={provider: lambda *args: FrameLike() for provider in (
        EASTMONEY_PROVIDER, TENCENT_PROVIDER, SINA_PROVIDER,
        INDEX_PROVIDER, CALENDAR_PROVIDER,
    )})

    report = runner.run(quick=True)

    assert [report.providers[name].observations for name in (
        EASTMONEY_PROVIDER, TENCENT_PROVIDER, SINA_PROVIDER,
        INDEX_PROVIDER, CALENDAR_PROVIDER,
    )] == [3, 3, 1, 1, 1]
    assert report.passed is False
    assert any("diagnostic" in reason.lower() for reason in report.reasons)


def test_probe_cli_writes_json_and_quick_mode_returns_diagnostic_exit(tmp_path) -> None:
    from scripts.probe_providers import main

    runner = ProviderProbeRunner(adapters={provider: lambda *args: FrameLike() for provider in (
        EASTMONEY_PROVIDER, TENCENT_PROVIDER, SINA_PROVIDER,
        INDEX_PROVIDER, CALENDAR_PROVIDER,
    )})
    output = tmp_path / "probe.json"

    exit_code = main(["--quick", "--output", str(output)], runner=runner)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 2
    assert payload["passed"] is False
    assert "diagnostic" in " ".join(payload["reasons"]).lower()

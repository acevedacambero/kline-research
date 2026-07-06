import json
from dataclasses import FrozenInstanceError

import pandas as pd
import pytest
import requests

from kline.ops.provider_probe import (
    CALENDAR_PROVIDER,
    EASTMONEY_PROVIDER,
    FACTOR_PROVIDER,
    INDEX_PROVIDER,
    SINA_PROVIDER,
    TENCENT_PROVIDER,
    ProviderProbeRunner,
    classify_error,
    percentile,
)


REQUIRED_FIELDS = ("open", "high", "low", "close", "volume")


class FrameLike:
    columns = REQUIRED_FIELDS

    def __len__(self):
        return 5


def factors(*_args):
    return pd.DataFrame([{"qfq_factor": 1.0, "hfq_factor": 1.0}])


def adapters(default=lambda *_args: FrameLike()):
    return {
        TENCENT_PROVIDER: default,
        INDEX_PROVIDER: default,
        FACTOR_PROVIDER: factors,
        SINA_PROVIDER: default,
        CALENDAR_PROVIDER: lambda *_args: [object()],
        EASTMONEY_PROVIDER: default,
    }


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
def test_classify_error_uses_stable_categories(error, category):
    assert classify_error(error) == category


def test_percentile_interpolates_and_handles_empty_values():
    assert percentile([], 95) == 0.0
    assert percentile([1.0, 2.0], 95) == pytest.approx(1.95)
    assert percentile([1.0, 2.0, 3.0, 4.0], 50) == pytest.approx(2.5)


@pytest.mark.parametrize("percent", [-0.1, 100.1])
def test_percentile_rejects_invalid_percent(percent):
    with pytest.raises(ValueError, match="between 0 and 100"):
        percentile([], percent)


def test_probe_models_and_nested_mappings_are_immutable():
    report = ProviderProbeRunner(adapters=adapters()).run()
    with pytest.raises(FrozenInstanceError):
        report.passed = False  # type: ignore[misc]
    with pytest.raises(TypeError):
        report.required_checks["tencentStocks"] = False  # type: ignore[index]


def test_full_runner_executes_exact_v2_target_counts():
    calls = []

    def bars(*args):
        calls.append(args)
        return FrameLike()

    probe_adapters = adapters(bars)
    probe_adapters[FACTOR_PROVIDER] = lambda *args: (calls.append(args) or factors())
    probe_adapters[CALENDAR_PROVIDER] = lambda *args: (calls.append(args) or [object()])
    runner = ProviderProbeRunner(adapters=probe_adapters)

    report = runner.run()

    assert {name: summary.observations for name, summary in report.providers.items()} == {
        TENCENT_PROVIDER: 10,
        INDEX_PROVIDER: 2,
        FACTOR_PROVIDER: 6,
        SINA_PROVIDER: 2,
        CALENDAR_PROVIDER: 1,
        EASTMONEY_PROVIDER: 10,
    }
    assert len(calls) == 31
    assert report.passed is True
    assert json.loads(json.dumps(report.to_dict()))["gateVersion"] == "sh-sz-provider-g2-v2"


def test_runner_records_failures_without_aborting():
    attempts = 0

    def flaky(*_args):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("late")
        return FrameLike()

    probe_adapters = adapters(flaky)
    report = ProviderProbeRunner(adapters=probe_adapters).run()

    assert attempts == 24
    assert report.providers[TENCENT_PROVIDER].error_categories == {"timeout": 1}
    assert len(report.observations) == 31


def test_wrapped_transport_error_category_is_preserved():
    def failed(*_args):
        try:
            raise ConnectionError("offline")
        except Exception as exc:
            raise RuntimeError("attempts exhausted") from exc

    probe_adapters = adapters()
    probe_adapters[TENCENT_PROVIDER] = failed
    report = ProviderProbeRunner(adapters=probe_adapters).run(quick=True)
    assert all(
        item.error_type == "network"
        for item in report.observations if item.provider == TENCENT_PROVIDER
    )


def test_quick_runner_is_diagnostic_and_never_passes():
    report = ProviderProbeRunner(adapters=adapters()).run(quick=True)
    assert report.passed is False
    assert any("diagnostic" in reason.lower() for reason in report.reasons)
    assert all("bj" not in item.security.lower() for item in report.observations)


def test_cli_writes_detached_json_and_returns_v2_gate_status(tmp_path):
    from scripts.probe_providers import main

    output = tmp_path / "probe.json"
    exit_code = main(
        ["--output", str(output)], runner=ProviderProbeRunner(adapters=adapters())
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["passed"] is True
    assert payload["requiredChecks"]["tencentIndexes"] is True


def test_quick_cli_always_returns_diagnostic_exit(tmp_path):
    from scripts.probe_providers import main

    output = tmp_path / "probe.json"
    exit_code = main(
        ["--quick", "--output", str(output)],
        runner=ProviderProbeRunner(adapters=adapters()),
    )
    assert exit_code == 2


def test_explicit_index_adapter_does_not_call_fallback():
    class Client:
        fallback_called = False

        def index_zh_a_hist(self, **_kwargs):
            raise ConnectionError("down")

        def stock_zh_index_daily(self, **_kwargs):
            self.fallback_called = True
            return FrameLike()

    client = Client()
    probe_adapters = adapters()
    probe_adapters[INDEX_PROVIDER] = ProviderProbeRunner.index_adapter(client)
    report = ProviderProbeRunner(adapters=probe_adapters).run(quick=True)
    assert all(
        not item.success for item in report.observations if item.provider == INDEX_PROVIDER
    )
    assert client.fallback_called is False

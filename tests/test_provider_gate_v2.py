from kline.ops.provider_probe import (
    CALENDAR_PROVIDER,
    EASTMONEY_PROVIDER,
    FACTOR_PROVIDER,
    GATE_VERSION,
    INDEX_PROVIDER,
    SINA_PROVIDER,
    TENCENT_PROVIDER,
    ProbeObservation,
    evaluate_gate,
)


def obs(provider, security, success=True, **kwargs):
    return ProbeObservation(
        provider=provider,
        security=security,
        success=success,
        elapsed_seconds=0.1,
        rows=kwargs.pop("rows", 10 if success else 0),
        error_type=None if success else "network",
        **kwargs,
    )


def passing_v2():
    return [
        *[obs(TENCENT_PROVIDER, f"sh60000{i}") for i in range(5)],
        *[obs(TENCENT_PROVIDER, f"sz00000{i}") for i in range(5)],
        obs(INDEX_PROVIDER, "sh000001"),
        obs(INDEX_PROVIDER, "sz399001"),
        *[
            obs(
                FACTOR_PROVIDER,
                security,
                factor_coverage_complete=True,
                factor_values_valid=True,
            )
            for security in ("sh600000", "sz000001", "sh688981", "sz300750", "sh600519", "sz002594")
        ],
        obs(SINA_PROVIDER, "sh600000"),
        obs(SINA_PROVIDER, "sz000001"),
        obs(CALENDAR_PROVIDER, "trading-calendar"),
        *[obs(EASTMONEY_PROVIDER, f"diagnostic-{i}", success=False) for i in range(10)],
    ]


def test_eastmoney_failure_is_warning_only_for_v2_gate():
    report = evaluate_gate(passing_v2())

    assert report.gate_version == GATE_VERSION == "sh-sz-provider-g2-v2"
    assert report.passed is True
    assert report.reasons == ()
    assert report.required_checks["tencentStocks"] is True
    assert report.diagnostic_checks["eastmoney"] is False
    assert any("EastMoney" in warning for warning in report.warnings)
    assert all("bj" not in item.security.lower() for item in report.observations)


def test_each_required_provider_failure_blocks_gate():
    for provider in (INDEX_PROVIDER, FACTOR_PROVIDER, SINA_PROVIDER, CALENDAR_PROVIDER):
        items = passing_v2()
        target = next(index for index, item in enumerate(items) if item.provider == provider)
        items[target] = obs(provider, items[target].security, success=False)

        report = evaluate_gate(items)

        assert report.passed is False
        assert report.reasons


def test_factor_coverage_and_values_are_required():
    items = passing_v2()
    target = next(index for index, item in enumerate(items) if item.provider == FACTOR_PROVIDER)
    items[target] = obs(
        FACTOR_PROVIDER,
        items[target].security,
        factor_coverage_complete=False,
        factor_values_valid=True,
    )

    report = evaluate_gate(items)

    assert report.passed is False
    assert report.required_checks["sinaFactors"] is False
    assert any("factor" in reason.lower() for reason in report.reasons)

from datetime import date

import pytest

from kline.p1 import (
    cluster_independent_periods,
    compute_drawdown_label,
    compute_forward_labels,
    compute_path_label,
    limit_rule,
    resolve_executable_entry,
    sample_eligibility,
)


def bars(count=280, start=10.0):
    return [
        {
            "date": date(2023, 1, 1).fromordinal(date(2023, 1, 1).toordinal() + i),
            "open_qfq": start,
            "high_qfq": start * 1.01,
            "low_qfq": start * 0.99,
            "close_qfq": start,
            "volume": 1000,
            "amount": 10000,
        }
        for i in range(count)
    ]


def test_limit_rule_covers_main_growth_bj_and_st():
    assert limit_rule("600000", date(2024, 1, 2), "sh", False).limit_width == 0.10
    assert limit_rule("300001", date(2024, 1, 2), "sz", False).limit_width == 0.20
    assert limit_rule("920001", date(2024, 1, 2), "bj", False).limit_width == 0.30
    assert limit_rule("600000", date(2024, 1, 2), "sh", True).limit_width == 0.05


def test_sample_eligibility_preserves_all_reasons_with_priority():
    result = sample_eligibility(bars(200), 180, rights_status="warn", no_limit=True)
    assert result.eligible is False
    assert result.status == "rights-warn"
    assert result.reasons == ["rights-warn", "insufficient-history", "noLimit-excluded"]


def test_executable_entry_delays_until_buyable_day():
    series = bars()
    signal = 250
    series[251]["open_qfq"] = 11.0
    series[251]["close_qfq"] = 11.0
    series[252]["open_qfq"] = 11.7

    entry = resolve_executable_entry(series, signal, code="600000", exchange="sh")

    assert entry.status == "delayed"
    assert entry.entry_index == 252
    assert entry.entry_delay == 2


def test_executable_entry_uses_raw_not_qfq_prices():
    series = bars()
    signal = 250
    series[250]["close"] = 10.0
    series[251]["open"] = 11.0
    series[250]["close_qfq"] = 10.0
    series[251]["open_qfq"] = 10.1
    series[251]["close"] = 11.0
    series[252]["open"] = 11.2
    result = resolve_executable_entry(series, signal, code="600000", exchange="sh")
    assert result.status == "delayed"
    assert result.entry_index == 252


def test_executable_entry_rejects_no_limit_window():
    series = bars()
    result = resolve_executable_entry(
        series, 250, code="600000", exchange="sh", no_limit_indices={251}
    )
    assert result.status == "noLimit-excluded"


def test_forward_labels_use_actual_entry_and_matching_benchmark_dates():
    series = bars()
    benchmark = bars(start=100.0)
    series[251]["open_qfq"] = 10.0
    series[256]["close_qfq"] = 11.0
    benchmark[251]["open_qfq"] = 100.0
    benchmark[256]["close_qfq"] = 105.0

    labels = compute_forward_labels(series, benchmark, 250, 251, [5])

    assert labels[5].executable_return == pytest.approx(0.1)
    assert round(labels[5].excess_executable_return, 8) == round(1.1 / 1.05 - 1, 8)


def test_path_same_day_double_hit_fails_conservatively():
    series = bars(30)
    series[1].update(high_qfq=11.2, low_qfq=9.4)
    result = compute_path_label(series, 1, 10.0, 20, 0.1, 0.05, True)
    assert result.success is False
    assert result.reason == "same-day-double-hit"


def test_drawdown_includes_entry_day_close():
    series = bars(30)
    series[1]["close_qfq"] = 9.4
    result = compute_drawdown_label(series, 1, 10.0, 20, 0.05)
    assert round(result.max_drawdown, 4) == -0.06
    assert result.hit_risk is True


def test_independent_periods_cluster_within_and_across_stocks():
    samples = [
        {"stock": "A", "condition": "x", "end_date": date(2024, 1, 1)},
        {"stock": "A", "condition": "x", "end_date": date(2024, 1, 5)},
        {"stock": "B", "condition": "x", "end_date": date(2024, 1, 3)},
        {"stock": "B", "condition": "x", "end_date": date(2024, 1, 20)},
    ]
    result = cluster_independent_periods(samples)
    assert result.independent_n == 2

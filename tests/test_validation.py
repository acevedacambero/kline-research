from datetime import date, timedelta

import pandas as pd

from kline.validation import calibrate_score, validate_single_factor, validate_top_score_portfolio
from kline.model import (
    train_multifeature_baseline,
    train_score_baseline,
    walk_forward_score_baseline,
)
from kline.model.baseline import binary_auc


def score_rows(count: int = 20) -> pd.DataFrame:
    start = date(2024, 1, 1)
    return pd.DataFrame(
        [
            {
                "exchange": "sh",
                "code": "600000",
                "date": start + timedelta(days=index),
                "score": index * 5,
                "usable": True,
                "score_definition_version": "p3-rule-score-v1",
            }
            for index in range(count)
        ]
    )


def label_rows(count: int = 20) -> pd.DataFrame:
    start = date(2024, 1, 1)
    return pd.DataFrame(
        [
            {
                "exchange": "sh",
                "code": "600000",
                "signal_date": start + timedelta(days=index),
                "p20_executable_return": -0.05 + index * 0.01,
                "path_success_p20": index >= count // 2,
                "max_drawdown_p20": -0.2 + index * 0.005,
                "label_maturity_date": start + timedelta(days=index + 30),
            }
            for index in range(count)
        ]
    )


def mature_label_rows(count: int = 20) -> pd.DataFrame:
    labels = label_rows(count)
    labels["label_maturity_date"] = labels["signal_date"]
    return labels


def test_single_factor_validation_buckets_scores_against_mature_labels():
    result = validate_single_factor(
        score_rows(),
        label_rows(),
        factor_column="score",
        label_column="p20_executable_return",
        buckets=4,
        as_of_date=date(2024, 3, 1),
    )

    assert result["factorColumn"] == "score"
    assert result["labelColumn"] == "p20_executable_return"
    assert result["sampleCount"] == 20
    assert result["independentPeriodCount"] == 1
    assert result["independenceGapDays"] == 7
    assert len(result["buckets"]) == 4
    assert result["buckets"][0]["count"] == 5
    assert result["buckets"][0]["avgLabel"] < result["buckets"][-1]["avgLabel"]
    assert result["buckets"][-1]["winRate"] == 1.0
    assert result["rankCorrelation"] > 0.9
    assert result["rankCorrelationInterval"]["lower"] > 0.8
    assert result["buckets"][0]["avgLabelInterval"]["lower"] <= result["buckets"][0]["avgLabel"]
    assert result["buckets"][-1]["winRateInterval"]["upper"] == 1.0
    assert result["stability"]["status"] == "stable"
    assert len(result["stability"]["periods"]) == 3
    assert result["multipleTesting"]["method"] == "benjamini-hochberg"


def test_single_factor_validation_filters_unusable_and_immature_samples():
    scores = score_rows()
    scores.loc[0, "usable"] = False
    labels = label_rows()
    labels.loc[1, "label_maturity_date"] = date(2024, 12, 1)

    result = validate_single_factor(
        scores,
        labels,
        factor_column="score",
        label_column="p20_executable_return",
        buckets=5,
        as_of_date=date(2024, 3, 1),
    )

    assert result["sampleCount"] == 18
    assert result["dropped"]["unusable"] == 1
    assert result["dropped"]["immature"] == 1


def test_single_factor_validation_reports_missing_columns():
    result = validate_single_factor(
        pd.DataFrame([{"exchange": "sh"}]),
        pd.DataFrame([{"exchange": "sh"}]),
        factor_column="score",
        label_column="p20_executable_return",
    )

    assert result["sampleCount"] == 0
    assert "score.score" in result["missingColumns"]
    assert "label.p20_executable_return" in result["missingColumns"]


def test_score_calibration_buckets_observed_positive_probability():
    result = calibrate_score(score_rows(), label_rows(), buckets=4, as_of_date=date(2024, 3, 1))
    assert result["version"] == "p5-score-calibration-v3-quality"
    assert result["sampleCount"] == 20
    assert len(result["buckets"]) == 4
    assert (
        result["buckets"][0]["observedProbability"] < result["buckets"][-1]["observedProbability"]
    )
    assert result["reliability"]["status"] == "review"
    assert result["reliability"]["warnings"]
    assert result["buckets"][0]["observedProbabilityInterval"]["confidence"] == 0.95
    assert result["buckets"][0]["avgLabelInterval"]["lower"] <= result["buckets"][0]["avgLabel"]
    assert 0 <= result["quality"]["brierScore"] <= 1
    assert result["quality"]["logLoss"] > 0
    assert 0 <= result["quality"]["expectedCalibrationError"] <= 1


def test_score_baseline_trains_time_split_model():
    scores = score_rows(40)
    labels = label_rows(40)
    labels["label_maturity_date"] = labels["signal_date"]
    result = train_score_baseline(scores, labels, train_until=date(2024, 1, 28))
    assert result["version"] == "p7-score-logistic-v1"
    assert result["status"] == "trained"
    assert result["trainCount"] == 28
    assert result["testCount"] == 12
    assert result["coefficient"] > 0


def test_binary_auc_matches_perfect_ranking():
    assert (
        binary_auc(pd.Series([0, 0, 1, 1]).to_numpy(), pd.Series([0.1, 0.2, 0.8, 0.9]).to_numpy())
        == 1.0
    )


def test_multifeature_baseline_trains_with_p2_columns():
    scores = score_rows(40)
    features = scores[["exchange", "code", "date"]].copy()
    features["bullish_alignment"] = True
    features["return_20"] = features.index / 100
    features["volume_ratio_5"] = 1.0
    features["volatility_20"] = 0.1
    labels = label_rows(40)
    labels["label_maturity_date"] = labels["signal_date"]
    result = train_multifeature_baseline(scores, labels, features, train_until=date(2024, 1, 30))
    assert result["version"] == "p7-multifeature-logistic-v1"
    assert result["trainCount"] == 30
    assert set(result["weights"]) == {
        "score",
        "bullish_alignment",
        "return_20",
        "volume_ratio_5",
        "volatility_20",
    }


def test_score_baseline_excludes_labels_immature_at_training_cutoff():
    result = train_score_baseline(score_rows(40), label_rows(40), train_until=date(2024, 1, 28))
    assert result["trainCount"] == 0
    assert result["status"] == "insufficient_data"


def test_score_baseline_purges_embargo_window_and_reports_leakage_audit():
    labels = mature_label_rows(50)
    result = train_score_baseline(
        score_rows(50), labels, train_until=date(2024, 1, 30), embargo_days=7
    )
    assert result["isolation"]["version"] == "purged-embargo-v1"
    assert result["isolation"]["embargoedSamples"] == 7
    assert result["testCount"] == 13


def test_walk_forward_returns_multiple_time_folds():
    labels = label_rows(80)
    labels["label_maturity_date"] = labels["signal_date"]
    result = walk_forward_score_baseline(score_rows(80), labels, folds=3)
    assert result["version"] == "p7-walk-forward-v2-nonoverlap"
    assert len(result["folds"]) == 3
    assert result["folds"][0]["testUntil"] == result["folds"][1]["trainUntil"]
    assert result["folds"][1]["testUntil"] == result["folds"][2]["trainUntil"]


def test_walk_forward_cutoffs_follow_mature_label_dates_not_future_scores():
    labels = label_rows(80)
    labels["label_maturity_date"] = labels["signal_date"]
    result = walk_forward_score_baseline(score_rows(140), labels, folds=3)

    assert all(fold["testCount"] > 0 for fold in result["folds"])
    assert result["folds"][-1]["testUntil"] <= labels["signal_date"].max()


def test_walk_forward_windows_allow_long_horizon_labels_to_mature():
    labels = label_rows(365)
    labels["label_maturity_date"] = labels["signal_date"] + pd.to_timedelta(60, unit="D")
    result = walk_forward_score_baseline(score_rows(365), labels, folds=3)

    assert all(fold["testCount"] > 0 for fold in result["folds"])


def test_top_score_portfolio_reports_excess_return():
    result = validate_top_score_portfolio(score_rows(20), mature_label_rows(20), top_fraction=0.2)
    assert result["version"] == "p8-top-score-portfolio-v4-benchmark"
    assert result["selectedCount"] > 0
    assert result["tradingDayCount"] == 20
    assert result["maxDrawdown"] is None
    assert result["excessReturn"] is not None
    assert any("重叠" in warning for warning in result["warnings"])


def test_delayed_exit_portfolio_does_not_claim_exit_delay_is_ignored():
    labels = mature_label_rows(20).rename(
        columns={"p20_executable_return": "p20_delayed_executable_return"}
    )
    result = validate_top_score_portfolio(
        score_rows(20), labels, label_column="p20_delayed_executable_return"
    )
    assert not any("未模拟不可卖顺延" in warning for warning in result["warnings"])


def test_top_score_portfolio_warns_on_small_selection():
    result = validate_top_score_portfolio(score_rows(5), mature_label_rows(5), top_fraction=0.2)
    assert any("少于 20" in warning for warning in result["warnings"])


def test_portfolio_excludes_labels_immature_at_as_of_date():
    result = validate_top_score_portfolio(
        score_rows(10), label_rows(10), as_of_date=date(2024, 1, 15)
    )
    assert result["sampleCount"] == 0


def test_validations_default_to_latest_available_score_date_for_maturity():
    scores = score_rows(40)
    labels = label_rows(20)

    single = validate_single_factor(
        scores, labels, factor_column="score", label_column="p20_executable_return"
    )
    calibration = calibrate_score(scores, labels)
    portfolio = validate_top_score_portfolio(scores, labels)

    assert single["sampleCount"] == 10
    assert calibration["sampleCount"] == 10
    assert portfolio["sampleCount"] == 10


def test_non_overlapping_portfolio_computes_drawdown():
    result = validate_top_score_portfolio(
        score_rows(40), mature_label_rows(40), non_overlapping=True
    )
    assert result["nonOverlapping"] is True
    assert result["tradingDayCount"] == 2
    assert result["maxDrawdown"] is not None
    assert result["annualizedReturn"] is not None
    assert result["annualizedVolatility"] is not None
    assert result["sharpeRatio"] is not None
    assert len(result["equityCurve"]) == result["tradingDayCount"]
    assert len(result["benchmarkEquityCurve"]) == result["tradingDayCount"]


def test_portfolio_reports_net_returns_after_costs():
    result = validate_top_score_portfolio(
        score_rows(40),
        label_rows(40),
        non_overlapping=True,
        transaction_cost_bps=10,
        slippage_bps=5,
    )
    assert result["totalCostRate"] == 0.0015
    assert result["netAverageReturn"] < result["averageReturn"]

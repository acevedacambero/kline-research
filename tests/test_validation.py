from datetime import date, timedelta

import pandas as pd

from kline.validation import calibrate_score, validate_single_factor
from kline.model import train_score_baseline


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
    assert len(result["buckets"]) == 4
    assert result["buckets"][0]["count"] == 5
    assert result["buckets"][0]["avgLabel"] < result["buckets"][-1]["avgLabel"]
    assert result["buckets"][-1]["winRate"] == 1.0
    assert result["rankCorrelation"] > 0.9


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
    assert result["version"] == "p5-score-calibration-v1"
    assert result["sampleCount"] == 20
    assert len(result["buckets"]) == 4
    assert result["buckets"][0]["observedProbability"] < result["buckets"][-1]["observedProbability"]
    assert result["reliability"]["status"] == "review"
    assert result["reliability"]["warnings"]


def test_score_baseline_trains_time_split_model():
    scores = score_rows(40)
    labels = label_rows(40)
    result = train_score_baseline(scores, labels, train_until=date(2024, 1, 28))
    assert result["version"] == "p7-score-logistic-v1"
    assert result["status"] == "trained"
    assert result["trainCount"] == 28
    assert result["testCount"] == 12
    assert result["coefficient"] > 0

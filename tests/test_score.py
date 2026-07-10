from kline.score import SCORE_DEFINITION_VERSION, compute_rule_score


def test_rule_score_is_point_in_time_and_explains_components():
    features = {
        "available_history": 260,
        "bullish_alignment": True,
        "bearish_alignment": False,
        "ma20_slope": 0.04,
        "close_to_ma20": 0.03,
        "range_position_60": 0.72,
        "drawdown_from_high_60": -0.08,
        "return_20": 0.08,
        "return_60": 0.18,
        "return_5": 0.03,
        "volume_ratio_5": 1.6,
        "volatility_20": 0.025,
        "limit_up_count_20": 2,
        "locked_limit_up_streak": 0,
        "gap_open": 0.01,
        "suspension_gap_days": 0,
        "is_approx": False,
    }

    score = compute_rule_score(features)

    assert score["version"] == SCORE_DEFINITION_VERSION
    assert score["score"] >= 80
    assert score["grade"] == "A"
    assert set(score["components"]) == {
        "trend", "position", "momentum", "volumePrice", "tradingBehavior"
    }
    assert score["components"]["trend"]["score"] > 20
    assert any("多头" in reason for reason in score["components"]["trend"]["reasons"])


def test_rule_score_keeps_missing_history_auditable():
    score = compute_rule_score({"available_history": 40})

    assert score["score"] < 30
    assert score["grade"] == "D"
    assert score["usable"] is False
    assert "available_history<120" in score["reasons"]
    assert score["components"]["trend"]["available"] is False


def test_rule_score_penalizes_untradable_path_risk():
    score = compute_rule_score(
        {
            "available_history": 260,
            "bullish_alignment": False,
            "bearish_alignment": True,
            "ma20_slope": -0.03,
            "close_to_ma20": -0.08,
            "range_position_60": 0.2,
            "drawdown_from_high_60": -0.35,
            "return_20": -0.1,
            "return_60": -0.2,
            "return_5": -0.05,
            "volume_ratio_5": 0.5,
            "volatility_20": 0.09,
            "limit_up_count_20": 8,
            "locked_limit_up_streak": 3,
            "gap_open": 0.09,
            "suspension_gap_days": 20,
            "is_approx": True,
            "rule_reason": "historical status inferred",
        }
    )

    assert score["score"] < 35
    assert score["grade"] == "D"
    assert "limit-rule-approx" in score["reasons"]
    assert score["components"]["tradingBehavior"]["score"] == 0

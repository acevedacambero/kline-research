from __future__ import annotations

import math
from typing import Any


SCORE_DEFINITION_VERSION = "p3-rule-score-v1"


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result):
        return None
    return result


def _bool(value: Any) -> bool:
    return bool(value) if value is not None else False


def _component(score: float, weight: int, reasons: list[str]) -> dict[str, Any]:
    bounded = max(0.0, min(float(weight), score))
    return {
        "score": round(bounded, 2),
        "weight": weight,
        "available": bool(reasons),
        "reasons": reasons,
    }


def _trend(row: dict[str, Any]) -> dict[str, Any]:
    score = 0.0
    reasons: list[str] = []
    slope = _number(row.get("ma20_slope"))
    close_to_ma20 = _number(row.get("close_to_ma20"))
    if _bool(row.get("bullish_alignment")):
        score += 10
        reasons.append("多头均线排列")
    if _bool(row.get("bearish_alignment")):
        score -= 8
        reasons.append("空头均线排列")
    if slope is not None:
        score += 8 if slope > 0.02 else 4 if slope > 0 else -4
        reasons.append("MA20 斜率为正" if slope > 0 else "MA20 斜率为负")
    if close_to_ma20 is not None:
        if -0.02 <= close_to_ma20 <= 0.08:
            score += 7
            reasons.append("价格贴近并站上 MA20")
        elif close_to_ma20 > 0.18:
            score -= 3
            reasons.append("价格偏离 MA20 过高")
        else:
            score += 2
            reasons.append("价格与 MA20 偏离可审计")
    return _component(score, 25, reasons)


def _position(row: dict[str, Any]) -> dict[str, Any]:
    score = 0.0
    reasons: list[str] = []
    position = _number(row.get("range_position_60"))
    drawdown = _number(row.get("drawdown_from_high_60"))
    if position is not None:
        if 0.55 <= position <= 0.9:
            score += 12
            reasons.append("位于 60 日区间强势区域")
        elif position > 0.9:
            score += 7
            reasons.append("接近 60 日高位")
        else:
            score += 3
            reasons.append("60 日区间位置偏低")
    if drawdown is not None:
        if drawdown >= -0.12:
            score += 8
            reasons.append("距离 60 日高点回撤可控")
        elif drawdown >= -0.25:
            score += 4
            reasons.append("60 日回撤中等")
        else:
            score -= 4
            reasons.append("60 日回撤较深")
    return _component(score, 20, reasons)


def _momentum(row: dict[str, Any]) -> dict[str, Any]:
    score = 0.0
    reasons: list[str] = []
    ret20 = _number(row.get("return_20"))
    ret60 = _number(row.get("return_60"))
    ret5 = _number(row.get("return_5"))
    if ret20 is not None:
        score += 10 if ret20 > 0.05 else 5 if ret20 > 0 else -5
        reasons.append("20 日动量为正" if ret20 > 0 else "20 日动量为负")
    if ret60 is not None:
        score += 10 if ret60 > 0.12 else 5 if ret60 > 0 else -5
        reasons.append("60 日动量为正" if ret60 > 0 else "60 日动量为负")
    if ret5 is not None:
        if -0.03 <= ret5 <= 0.08:
            score += 5
            reasons.append("5 日涨幅未过热")
        elif ret5 > 0.15:
            score -= 3
            reasons.append("5 日涨幅过热")
        else:
            reasons.append("5 日动量可审计")
    return _component(score, 25, reasons)


def _volume_price(row: dict[str, Any]) -> dict[str, Any]:
    score = 0.0
    reasons: list[str] = []
    volume_ratio = _number(row.get("volume_ratio_5"))
    volatility = _number(row.get("volatility_20"))
    if volume_ratio is not None:
        if 1.1 <= volume_ratio <= 3:
            score += 9
            reasons.append("量能温和放大")
        elif volume_ratio > 5:
            score -= 2
            reasons.append("量能异常放大")
        else:
            score += 3
            reasons.append("量能未明显放大")
    if volatility is not None:
        if volatility <= 0.04:
            score += 6
            reasons.append("20 日波动可控")
        elif volatility <= 0.08:
            score += 2
            reasons.append("20 日波动偏高")
        else:
            score -= 3
            reasons.append("20 日波动过高")
    return _component(score, 15, reasons)


def _trading_behavior(row: dict[str, Any]) -> dict[str, Any]:
    score = 8.0
    reasons = ["交易行为基础分"]
    limit_count = _number(row.get("limit_up_count_20"))
    locked_streak = _number(row.get("locked_limit_up_streak"))
    gap = _number(row.get("gap_open"))
    suspension_gap = _number(row.get("suspension_gap_days"))
    if limit_count is not None:
        if 1 <= limit_count <= 4:
            score += 5
            reasons.append("20 日内有涨停活跃度")
        elif limit_count > 6:
            score -= 5
            reasons.append("20 日涨停次数过多")
    if locked_streak is not None and locked_streak >= 2:
        score -= 6
        reasons.append("连续一字板降低可执行性")
    if gap is not None and abs(gap) > 0.07:
        score -= 4
        reasons.append("开盘跳空过大")
    if suspension_gap is not None and suspension_gap > 10:
        score -= 4
        reasons.append("存在较长停牌间隔")
    return _component(score, 15, reasons)


def _grade(score: float) -> str:
    if score >= 80:
        return "A"
    if score >= 65:
        return "B"
    if score >= 50:
        return "C"
    return "D"


def compute_rule_score(row: dict[str, Any]) -> dict[str, Any]:
    available_history = int(_number(row.get("available_history")) or 0)
    components = {
        "trend": _trend(row),
        "position": _position(row),
        "momentum": _momentum(row),
        "volumePrice": _volume_price(row),
        "tradingBehavior": _trading_behavior(row),
    }
    reasons: list[str] = []
    if available_history < 120:
        reasons.append("available_history<120")
    if _bool(row.get("is_approx")):
        reasons.append("limit-rule-approx")
    if row.get("rule_reason"):
        reasons.append(str(row["rule_reason"]))

    score = round(sum(item["score"] for item in components.values()), 2)
    if available_history < 120:
        score = min(score, 29.0)
    if _bool(row.get("is_approx")):
        score = max(0.0, score - 5)
    return {
        "version": SCORE_DEFINITION_VERSION,
        "score": round(score, 2),
        "grade": _grade(score),
        "usable": available_history >= 120 and not _bool(row.get("is_approx")),
        "components": components,
        "reasons": reasons,
    }

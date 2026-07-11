"""Conviction synthesizer.

Fuses the market-level sub-analyses (regime, breadth, timing signals,
sector rotation, sentiment) into one 0-100 conviction score with an
explicit signal-convergence bonus — independent signals agreeing is
worth more than any single strong signal. Adapted from the
Druckenmiller-style synthesizer in claude-trading-skills.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from quantagent.tools.market_breadth import (
    compute_market_sentiment,
    count_distribution_days,
    detect_follow_through_day,
    detect_market_regime,
    exposure_band,
)
from quantagent.tools.providers.base import AbstractDataProvider
from quantagent.tools.sector_analysis import detect_sector_rotation

logger = logging.getLogger(__name__)

_WEIGHTS: dict[str, float] = {
    "regime": 0.30,
    "breadth": 0.15,
    "timing": 0.20,
    "rotation": 0.15,
    "sentiment": 0.10,
    "convergence": 0.10,
}

_STANCES: list[tuple[float, str]] = [
    (80.0, "aggressive"),
    (60.0, "constructive"),
    (40.0, "selective"),
    (20.0, "defensive"),
]

_DISTRIBUTION_SCORES = {"healthy": 80.0, "caution": 50.0, "under-pressure": 20.0}
_FTD_ADJUST = {"confirmed-uptrend": 15.0, "rally-attempt": 0.0, "correction": -15.0}
_ROTATION_SCORES = {"risk-on": 75.0, "neutral": 50.0, "risk-off": 25.0}


async def synthesize_conviction(
    provider: AbstractDataProvider,
    universe: str = "sp500",
) -> dict:
    """Fuse regime, breadth, timing, rotation, and sentiment into one score.

    Args:
        provider: Market data provider.
        universe: Universe for regime/breadth components.

    Returns:
        Dict: {conviction_score (0-100), stance, recommended_exposure,
        components: {name: {score, weight, signal}}, convergence, key_risks}.
    """
    regime, dist, ftd, rotation, sentiment = await asyncio.gather(
        detect_market_regime(provider, universe=universe),
        count_distribution_days(provider),
        detect_follow_through_day(provider),
        detect_sector_rotation(provider),
        compute_market_sentiment(provider),
    )
    components = _component_scores(regime, dist, ftd, rotation, sentiment)
    convergence = _convergence(components)
    components["convergence"] = {
        "score": convergence["bonus"],
        "weight": _WEIGHTS["convergence"],
        "signal": f"{convergence['agreeing']}/{convergence['total']} components agree",
    }
    score = round(
        sum(c["score"] * c["weight"] for c in components.values()), 2
    )
    return {
        "conviction_score": score,
        "stance": _stance(score),
        "recommended_exposure": exposure_band(score),
        "components": components,
        "convergence": convergence,
        "key_risks": _key_risks(regime, dist, ftd, rotation, sentiment),
        "as_of": datetime.now(UTC).date().isoformat(),
    }


def _component_scores(
    regime: dict, dist: dict, ftd: dict, rotation: dict, sentiment: dict
) -> dict[str, dict]:
    """Score each sub-analysis on a 0-100 scale."""
    breadth_raw = regime.get("components", {}).get("scores", {}).get("breadth")
    breadth_score = round((breadth_raw + 1) * 50, 2) if breadth_raw is not None else 50.0
    timing = _clip(
        _DISTRIBUTION_SCORES.get(str(dist.get("signal")), 50.0)
        + _FTD_ADJUST.get(str(ftd.get("status")), 0.0)
    )
    return {
        "regime": {
            "score": float(regime.get("score", 50.0)),
            "weight": _WEIGHTS["regime"],
            "signal": regime.get("regime", "unknown"),
        },
        "breadth": {
            "score": breadth_score,
            "weight": _WEIGHTS["breadth"],
            "signal": regime.get("components", {}).get("breadth_health", "unknown"),
        },
        "timing": {
            "score": timing,
            "weight": _WEIGHTS["timing"],
            "signal": f"{dist.get('signal')} / {ftd.get('status')}",
        },
        "rotation": {
            "score": _ROTATION_SCORES.get(str(rotation.get("rotation_signal")), 50.0),
            "weight": _WEIGHTS["rotation"],
            "signal": rotation.get("rotation_signal", "unknown"),
        },
        "sentiment": {
            "score": _clip((sentiment.get("score", 0.0) + 100) / 2),
            "weight": _WEIGHTS["sentiment"],
            "signal": sentiment.get("label", "unknown"),
        },
    }


def _clip(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 2)


def _convergence(components: dict[str, dict]) -> dict:
    """Reward directional agreement across independent components."""
    sides = [c["score"] >= 50 for c in components.values()]
    total = len(sides)
    agreeing = max(sum(sides), total - sum(sides))
    bonus = round(agreeing / total * 100, 2) if total else 50.0
    return {"agreeing": agreeing, "total": total, "bonus": bonus}


def _stance(score: float) -> str:
    for threshold, stance in _STANCES:
        if score >= threshold:
            return stance
    return "risk-off"


def _key_risks(
    regime: dict, dist: dict, ftd: dict, rotation: dict, sentiment: dict
) -> list[str]:
    risks = []
    if dist.get("count", 0) >= 5:
        risks.append(
            f"{dist['count']} distribution days in {dist.get('lookback_days')} "
            "sessions — institutional selling pressure"
        )
    if ftd.get("status") == "correction":
        risks.append("Market in correction with no follow-through day yet")
    if regime.get("confidence", 1.0) < 0.6:
        risks.append("Regime components disagree — low-confidence reading")
    if rotation.get("rotation_signal") == "risk-off" and regime.get("regime") in (
        "bull",
        "strong-bull",
    ):
        risks.append("Defensive sector rotation diverging from bull regime")
    if sentiment.get("score", 0) > 60:
        risks.append("Sentiment at extreme greed — complacency risk")
    if sentiment.get("score", 0) < -60:
        risks.append("Sentiment at extreme fear — expect high volatility")
    return risks

"""Tests for the conviction synthesizer."""
from __future__ import annotations

import numpy as np
import pandas as pd
from _synthetic import SyntheticProvider, make_ohlcv, trend_close

from quantagent.tools.conviction import (
    _convergence,
    _stance,
    synthesize_conviction,
)
from quantagent.tools.universe import SECTOR_ETFS


def _conviction_provider(bullish: bool) -> SyntheticProvider:
    strong, weak = (0.002, -0.002) if bullish else (-0.002, 0.002)
    frames: dict[str, pd.DataFrame] = {
        "SPY": make_ohlcv(trend_close(drift=strong)),
        "RSP": make_ohlcv(trend_close(drift=strong * 1.5)),
        "IWM": make_ohlcv(trend_close(drift=strong * 1.5)),
        "XLY": make_ohlcv(trend_close(drift=strong * 1.5)),
        "XLP": make_ohlcv(trend_close(drift=weak)),
        "TLT": make_ohlcv(trend_close(drift=weak)),
        "HYG": make_ohlcv(trend_close(drift=strong)),
        "LQD": make_ohlcv(trend_close(drift=weak)),
        "^VIX": make_ohlcv(np.full(120, 12.0 if bullish else 38.0)),
        "^VIX3M": make_ohlcv(np.full(120, 16.0 if bullish else 30.0)),
    }
    for i, etf in enumerate(SECTOR_ETFS.values()):
        drift = strong if etf not in ("XLP", "XLU", "XLV") else strong * 0.2
        frames.setdefault(etf, make_ohlcv(trend_close(drift=drift, seed=i)))
    return SyntheticProvider(frames)


async def test_conviction_bullish() -> None:
    result = await synthesize_conviction(_conviction_provider(bullish=True))
    assert result["conviction_score"] > 60
    assert result["stance"] in {"aggressive", "constructive"}
    assert result["recommended_exposure"]["min_pct"] >= 70
    assert set(result["components"]) == {
        "regime", "breadth", "timing", "rotation", "sentiment", "convergence",
    }
    weights = [c["weight"] for c in result["components"].values()]
    assert sum(weights) == 1.0


async def test_conviction_bearish() -> None:
    result = await synthesize_conviction(_conviction_provider(bullish=False))
    assert result["conviction_score"] < 45
    assert result["stance"] in {"selective", "defensive", "risk-off"}
    assert result["key_risks"]  # bear tape should surface at least one risk


async def test_conviction_convergence_reported() -> None:
    result = await synthesize_conviction(_conviction_provider(bullish=True))
    convergence = result["convergence"]
    assert convergence["total"] == 5
    assert 0 < convergence["agreeing"] <= 5
    assert convergence["bonus"] == round(
        convergence["agreeing"] / convergence["total"] * 100, 2
    )


def test_stance_bands() -> None:
    assert _stance(90) == "aggressive"
    assert _stance(70) == "constructive"
    assert _stance(50) == "selective"
    assert _stance(30) == "defensive"
    assert _stance(10) == "risk-off"


def test_convergence_unanimous() -> None:
    components = {n: {"score": 80.0} for n in ("a", "b", "c")}
    result = _convergence(components)
    assert result == {"agreeing": 3, "total": 3, "bonus": 100.0}


def test_convergence_split() -> None:
    components = {"a": {"score": 80.0}, "b": {"score": 20.0}}
    result = _convergence(components)
    assert result["agreeing"] == 1
    assert result["bonus"] == 50.0

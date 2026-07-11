"""Tests for pair trading tools."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from _synthetic import SyntheticProvider, make_ohlcv

from quantagent.tools import screener
from quantagent.tools.pair_trading import (
    _half_life,
    _spread_signal,
    compute_spread_metrics,
    find_cointegrated_pairs,
)


def _random_walk(n: int = 300, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 100.0 + np.cumsum(rng.normal(0, 1.0, n))


def _cointegrated_partner(a: np.ndarray, seed: int = 2) -> np.ndarray:
    rng = np.random.default_rng(seed)
    # b = (a - 5) / 2 + noise  =>  a ≈ 2b + 5, hedge ratio ~2.
    return (a - 5.0) / 2.0 + rng.normal(0, 0.3, len(a))


def _pair_provider() -> SyntheticProvider:
    a = _random_walk(seed=1)
    frames = {
        "AAA": make_ohlcv(a),
        "BBB": make_ohlcv(_cointegrated_partner(a)),
        "ZZZ": make_ohlcv(_random_walk(seed=99)),  # independent walk
    }
    return SyntheticProvider(frames)


@pytest.fixture
def patched_universe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        screener, "_fetch_universe_tickers", lambda universe: ["AAA", "BBB", "ZZZ"]
    )


async def test_finds_cointegrated_pair(patched_universe: None) -> None:
    df = await find_cointegrated_pairs(_pair_provider(), min_correlation=0.0)
    assert len(df) >= 1
    top = df.iloc[0]
    assert {top["symbol_a"], top["symbol_b"]} == {"AAA", "BBB"}
    assert top["coint_pvalue"] < 0.05
    assert top["hedge_ratio"] == pytest.approx(2.0, abs=0.2)
    assert top["half_life_days"] is not None and top["half_life_days"] > 0


async def test_correlation_prefilter_blocks_everything(patched_universe: None) -> None:
    df = await find_cointegrated_pairs(_pair_provider(), min_correlation=1.01)
    assert df.empty


async def test_sector_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        screener, "_fetch_universe_tickers", lambda universe: ["AAA", "BBB", "ZZZ"]
    )
    provider = _pair_provider()
    provider.classifications = {
        "AAA": {"symbol": "AAA", "sector": "Energy", "industry": "Oil"},
        "BBB": {"symbol": "BBB", "sector": "Energy", "industry": "Oil"},
        "ZZZ": {"symbol": "ZZZ", "sector": "Utilities", "industry": "Electric"},
    }
    df = await find_cointegrated_pairs(provider, sector="energy", min_correlation=0.0)
    assert not df.empty
    symbols = set(df["symbol_a"]) | set(df["symbol_b"])
    assert "ZZZ" not in symbols


async def test_short_history_symbols_skipped(patched_universe: None) -> None:
    provider = _pair_provider()
    provider.frames["BBB"] = make_ohlcv([100.0] * 10)  # too short
    df = await find_cointegrated_pairs(provider, min_correlation=0.0)
    assert df.empty or "BBB" not in (set(df["symbol_a"]) | set(df["symbol_b"]))


async def test_too_few_symbols(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(screener, "_fetch_universe_tickers", lambda universe: ["AAA"])
    df = await find_cointegrated_pairs(_pair_provider())
    assert df.empty


async def test_spread_metrics_structure() -> None:
    provider = _pair_provider()
    result = await compute_spread_metrics(provider, "aaa", "bbb")
    assert result["symbol_a"] == "AAA"
    assert result["hedge_ratio"] == pytest.approx(2.0, abs=0.2)
    assert result["coint_pvalue"] < 0.05
    assert -5 < result["current_zscore"] < 5
    assert result["half_life_days"] > 0
    assert isinstance(result["signal"], str)


async def test_spread_metrics_insufficient_history() -> None:
    provider = SyntheticProvider({"AAA": make_ohlcv([100.0] * 10)})
    with pytest.raises(ValueError):
        await compute_spread_metrics(provider, "AAA", "BBB")


def test_spread_signal_bands() -> None:
    assert "short AAA, long BBB" in _spread_signal(2.5, "AAA", "BBB")
    assert "long AAA, short BBB" in _spread_signal(-2.5, "AAA", "BBB")
    assert _spread_signal(0.2, "AAA", "BBB").startswith("exit-zone")
    assert _spread_signal(1.2, "AAA", "BBB") == "neutral"


def test_half_life_of_mean_reverting_series() -> None:
    rng = np.random.default_rng(7)
    spread = [0.0]
    for _ in range(299):
        spread.append(spread[-1] * 0.9 + rng.normal(0, 0.1))
    hl = _half_life(pd.Series(spread))
    # AR(1) coefficient 0.9 -> half-life ~ ln(2)/ln(1/0.9) ≈ 6.6 days.
    assert hl == pytest.approx(6.6, abs=2.0)


def test_half_life_none_for_trending_series() -> None:
    trending = pd.Series(np.linspace(0, 100, 300))
    assert _half_life(trending) is None

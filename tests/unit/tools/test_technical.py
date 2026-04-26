"""Tests for technical analysis tools."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pandas_ta as ta  # noqa: F401  # registers .ta accessor on DataFrame

from quantagent.tools.technical import (
    compute_correlation_matrix,
    compute_indicators,
    detect_patterns,
    detect_support_resistance,
    generate_signals,
    summarize_technicals,
)


def _synthetic_ohlcv(n: int = 100, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    trend = np.linspace(100, 120, n)
    noise = rng.normal(0, 2, n)
    close = trend + noise
    high = close + rng.uniform(0, 2, n)
    low = close - rng.uniform(0, 2, n)
    open_ = close + rng.normal(0, 1, n)
    volume = rng.integers(1_000_000, 5_000_000, n)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=dates,
    )


def test_compute_indicators():
    df = _synthetic_ohlcv()
    result = compute_indicators(df, ["sma_20", "rsi_14", "macd"])
    assert "SMA_20" in result.columns
    assert "RSI_14" in result.columns
    assert "MACD_12_26_9" in result.columns


def test_detect_patterns():
    # Create a doji pattern
    df = _synthetic_ohlcv(n=10)
    df.loc[df.index[5], "Open"] = 100.0
    df.loc[df.index[5], "High"] = 100.5
    df.loc[df.index[5], "Low"] = 99.5
    df.loc[df.index[5], "Close"] = 100.02
    patterns = detect_patterns(df)
    assert isinstance(patterns, list)
    # Should detect at least the doji we created
    doji = [p for p in patterns if p["pattern"] == "doji"]
    assert len(doji) >= 1


def test_detect_support_resistance():
    df = _synthetic_ohlcv(n=100)
    levels = detect_support_resistance(df)
    assert "support" in levels
    assert "resistance" in levels
    assert "current_price" in levels
    assert levels["current_price"] > 0


def test_generate_signals_sma_crossover():
    df = _synthetic_ohlcv(n=250)
    signals = generate_signals(df, "sma_crossover")
    assert "Signal" in signals.columns
    assert set(signals["Signal"].unique()).issubset({-1, 0, 1})


def test_generate_signals_unknown():
    df = _synthetic_ohlcv()
    signals = generate_signals(df, "unknown_strategy")
    assert (signals["Signal"] == 0).all()


def test_compute_correlation_matrix():
    df1 = _synthetic_ohlcv(n=50, seed=1)
    df2 = _synthetic_ohlcv(n=50, seed=2)
    corr = compute_correlation_matrix({"A": df1, "B": df2})
    assert corr.shape == (2, 2)
    assert corr.loc["A", "A"] == 1.0


def test_summarize_technicals():
    df = _synthetic_ohlcv(n=250)
    summary = summarize_technicals(df)
    assert "price" in summary
    assert "trend" in summary
    assert "momentum" in summary
    assert "volatility" in summary
    assert "volume" in summary


def test_summarize_technicals_insufficient_data():
    df = _synthetic_ohlcv(n=10)
    summary = summarize_technicals(df)
    assert "error" in summary

"""Tests for technical analysis tools."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pandas_ta as ta  # noqa: F401  # registers .ta accessor on DataFrame

from quantagent.tools.technical import (
    _deduplicate_levels,
    _detect_evening_star,
    _detect_hammer,
    _detect_morning_star,
    _detect_shooting_star,
    _detect_three_black_crows,
    _detect_three_white_soldiers,
    _dispatch_indicator,
    _signal_sma_crossover,
    _summarize_momentum,
    _summarize_trend,
    _summarize_volatility,
    _summarize_volume,
    compute_correlation_matrix,
    compute_indicators,
    detect_patterns,
    detect_support_resistance,
    generate_signals,
    summarize_technicals,
    wilder_rsi,
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


def test_compute_indicators() -> None:
    df = _synthetic_ohlcv()
    result = compute_indicators(df, ["sma_20", "rsi_14", "macd"])
    assert "SMA_20" in result.columns
    assert "RSI_14" in result.columns
    assert "MACD_12_26_9" in result.columns


def test_detect_patterns() -> None:
    df = _synthetic_ohlcv(n=10)
    df.loc[df.index[5], "Open"] = 100.0
    df.loc[df.index[5], "High"] = 100.5
    df.loc[df.index[5], "Low"] = 99.5
    df.loc[df.index[5], "Close"] = 100.02
    patterns = detect_patterns(df)
    assert isinstance(patterns, list)
    doji = [p for p in patterns if p["pattern"] == "doji"]
    assert len(doji) >= 1


def test_detect_support_resistance() -> None:
    df = _synthetic_ohlcv(n=100)
    levels = detect_support_resistance(df)
    assert "support" in levels
    assert "resistance" in levels
    assert "current_price" in levels
    assert levels["current_price"] > 0


def test_detect_support_resistance_small_window() -> None:
    df = _synthetic_ohlcv(n=5)
    levels = detect_support_resistance(df, window=20)
    assert "support" in levels


def test_generate_signals_sma_crossover() -> None:
    df = _synthetic_ohlcv(n=250)
    signals = generate_signals(df, "sma_crossover")
    assert "Signal" in signals.columns
    assert set(signals["Signal"].unique()).issubset({-1, 0, 1})


def test_generate_signals_buy_and_hold() -> None:
    df = _synthetic_ohlcv(n=50)
    signals = generate_signals(df, "buy_and_hold")
    assert signals["Signal"].iloc[0] == 1
    assert (signals["Signal"].iloc[1:] == 0).all()


def test_generate_signals_unknown() -> None:
    df = _synthetic_ohlcv()
    signals = generate_signals(df, "unknown_strategy")
    assert (signals["Signal"] == 0).all()


def test_compute_correlation_matrix() -> None:
    df1 = _synthetic_ohlcv(n=50, seed=1)
    df2 = _synthetic_ohlcv(n=50, seed=2)
    corr = compute_correlation_matrix({"A": df1, "B": df2})
    assert corr.shape == (2, 2)
    assert corr.loc["A", "A"] == 1.0


def test_summarize_technicals() -> None:
    df = _synthetic_ohlcv(n=250)
    summary = summarize_technicals(df)
    assert "price" in summary
    assert "trend" in summary
    assert "momentum" in summary
    assert "volatility" in summary
    assert "volume" in summary


def test_summarize_technicals_insufficient_data() -> None:
    df = _synthetic_ohlcv(n=10)
    summary = summarize_technicals(df)
    assert "error" in summary


def test_wilder_rsi() -> None:
    close = pd.Series([100.0, 101.0, 102.0, 101.5, 103.0, 104.0, 103.5, 105.0] * 5)
    rsi = wilder_rsi(close, length=14)
    assert rsi is not None
    assert 0 <= rsi <= 100


def test_wilder_rsi_insufficient_data() -> None:
    close = pd.Series([100.0, 101.0])
    assert wilder_rsi(close, length=14) is None


def test_wilder_rsi_all_gains() -> None:
    close = pd.Series(list(range(100, 130)))
    rsi = wilder_rsi(close, length=14)
    assert rsi is not None
    assert rsi == 100.0


def test_dispatch_indicator_unknown() -> None:
    df = _synthetic_ohlcv()
    # Should not raise, just log a warning
    _dispatch_indicator(df, "nonexistent_indicator")


def test_detect_hammer() -> None:
    df = _synthetic_ohlcv(n=30, seed=1)
    o, c = df["Open"], df["Close"]
    h, lo = df["High"], df["Low"]
    body = (c - o).abs()
    upper_shadow = h - np.maximum(o, c)
    lower_shadow = np.minimum(o, c) - lo
    patterns = _detect_hammer(df, o, c, upper_shadow, lower_shadow, body)
    assert isinstance(patterns, list)


def test_detect_shooting_star() -> None:
    df = _synthetic_ohlcv(n=30, seed=1)
    o, c = df["Open"], df["Close"]
    h, lo = df["High"], df["Low"]
    body = (c - o).abs()
    upper_shadow = h - np.maximum(o, c)
    lower_shadow = np.minimum(o, c) - lo
    patterns = _detect_shooting_star(df, o, c, upper_shadow, lower_shadow, body)
    assert isinstance(patterns, list)


def test_detect_morning_star() -> None:
    df = _synthetic_ohlcv(n=30, seed=42)
    o, c = df["Open"], df["Close"]
    body = (c - o).abs()
    patterns = _detect_morning_star(df, o, c, body)
    assert isinstance(patterns, list)


def test_detect_evening_star() -> None:
    df = _synthetic_ohlcv(n=30, seed=42)
    o, c = df["Open"], df["Close"]
    body = (c - o).abs()
    patterns = _detect_evening_star(df, o, c, body)
    assert isinstance(patterns, list)


def test_detect_three_white_soldiers() -> None:
    df = _synthetic_ohlcv(n=30, seed=42)
    o, c = df["Open"], df["Close"]
    body = (c - o).abs()
    patterns = _detect_three_white_soldiers(df, o, c, body)
    assert isinstance(patterns, list)


def test_detect_three_black_crows() -> None:
    df = _synthetic_ohlcv(n=30, seed=42)
    o, c = df["Open"], df["Close"]
    body = (c - o).abs()
    patterns = _detect_three_black_crows(df, o, c, body)
    assert isinstance(patterns, list)


def test_detect_patterns_short_df() -> None:
    df = _synthetic_ohlcv(n=2)
    patterns = detect_patterns(df)
    assert patterns == []


def test_dedup_levels() -> None:
    levels = [100.0, 100.5, 150.0, 151.0]
    result = _deduplicate_levels(levels, tolerance=0.01)
    assert len(result) == 2


def test_dedup_levels_empty() -> None:
    assert _deduplicate_levels([], tolerance=0.01) == []


def test_signal_sma_crossover() -> None:
    df = _synthetic_ohlcv(n=250)
    result = _signal_sma_crossover(df.copy())
    assert "Signal" in result.columns


def test_summarize_momentum_none() -> None:
    result = _summarize_momentum(None, None)
    assert result["rsi_14"] is None
    assert result["macd_signal"] is None


def test_summarize_trend_none_smas() -> None:
    close = pd.Series([100.0, 101.0])
    result = _summarize_trend(close, None, None, None)
    assert result["sma20"] is None


def test_summarize_volatility_none() -> None:
    close = pd.Series([100.0])
    result = _summarize_volatility(close, None, None, None)
    assert result["bb_position"] is None


def test_summarize_volume() -> None:
    df = _synthetic_ohlcv(n=30)
    result = _summarize_volume(df)
    assert "latest_volume" in result
    assert result["latest_volume"] > 0


def test_generate_signals_ema_crossover() -> None:
    df = _synthetic_ohlcv(n=250)
    signals = generate_signals(df, "ema_crossover")
    assert "Signal" in signals.columns


def test_generate_signals_rsi_mean_reversion() -> None:
    df = _synthetic_ohlcv(n=250)
    signals = generate_signals(df, "rsi_mean_reversion")
    assert "Signal" in signals.columns


def test_generate_signals_macd_momentum() -> None:
    df = _synthetic_ohlcv(n=250)
    signals = generate_signals(df, "macd_momentum")
    assert "Signal" in signals.columns


def test_generate_signals_bollinger_breakout() -> None:
    df = _synthetic_ohlcv(n=250)
    signals = generate_signals(df, "bollinger_breakout")
    assert "Signal" in signals.columns

"""Technical analysis tool functions."""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_indicators(df: pd.DataFrame, indicators: list[str]) -> pd.DataFrame:
    """Compute technical indicators on OHLCV data.

    Args:
        df: DataFrame with Open, High, Low, Close, Volume columns.
        indicators: List of indicator specs such as sma_20, ema_50, rsi_14,
            macd, bbands, atr_14, adx_14, obv, stoch, vwap, supertrend.

    Returns:
        Original DataFrame with indicator columns appended.
    """
    result = df.copy()
    for spec in indicators:
        spec = spec.lower().strip()
        try:
            if spec.startswith("sma_"):
                length = int(spec.split("_")[1])
                result.ta.sma(length=length, append=True)
            elif spec.startswith("ema_"):
                length = int(spec.split("_")[1])
                result.ta.ema(length=length, append=True)
            elif spec.startswith("rsi_"):
                length = int(spec.split("_")[1])
                result.ta.rsi(length=length, append=True)
            elif spec == "macd" or spec == "macd_signal" or spec == "macd_hist":
                result.ta.macd(append=True)
            elif spec.startswith("bbands_"):
                result.ta.bbands(append=True)
                # pandas-ta adds BBL, BBM, BBU columns
            elif spec.startswith("atr_"):
                length = int(spec.split("_")[1])
                result.ta.atr(length=length, append=True)
            elif spec.startswith("adx_"):
                length = int(spec.split("_")[1])
                result.ta.adx(length=length, append=True)
            elif spec == "obv":
                result.ta.obv(append=True)
            elif spec == "stoch_k" or spec == "stoch_d":
                result.ta.stoch(append=True)
            elif spec == "vwap":
                result.ta.vwap(append=True)
            elif spec == "supertrend":
                result.ta.supertrend(append=True)
            else:
                logger.warning("Unknown indicator: %s", spec)
        except Exception as exc:
            logger.warning("Failed to compute indicator %s: %s", spec, exc)
    return result


def detect_patterns(df: pd.DataFrame) -> list[dict]:
    """Detect candlestick patterns.

    Returns:
        List of dicts: {pattern, date, direction, strength}.
    """
    patterns: list[dict] = []
    if len(df) < 3:
        return patterns

    o = df["Open"]
    h = df["High"]
    lo = df["Low"]
    c = df["Close"]
    body = (c - o).abs()
    range_ = h - lo
    upper_shadow = h - np.maximum(o, c)
    lower_shadow = np.minimum(o, c) - lo

    # Doji: body < 5% of range
    doji = body < (range_ * 0.05)
    for date in df.index[doji]:
        patterns.append(
            {"pattern": "doji", "date": date.isoformat(), "direction": "neutral", "strength": 1}
        )

    # Engulfing
    bullish_engulfing = (o.shift(1) > c.shift(1)) & (o < c) & (o <= c.shift(1)) & (c >= o.shift(1))
    bearish_engulfing = (o.shift(1) < c.shift(1)) & (o > c) & (o >= c.shift(1)) & (c <= o.shift(1))
    for date in df.index[bullish_engulfing]:
        patterns.append(
            {
                "pattern": "engulfing",
                "date": date.isoformat(),
                "direction": "bullish",
                "strength": 2,
            }
        )
    for date in df.index[bearish_engulfing]:
        patterns.append(
            {
                "pattern": "engulfing",
                "date": date.isoformat(),
                "direction": "bearish",
                "strength": 2,
            }
        )

    # Hammer
    hammer = (lower_shadow > body * 2) & (upper_shadow < body * 0.5) & (c > o)
    for date in df.index[hammer]:
        patterns.append(
            {"pattern": "hammer", "date": date.isoformat(), "direction": "bullish", "strength": 2}
        )

    # Shooting star
    shooting_star = (upper_shadow > body * 2) & (lower_shadow < body * 0.5) & (c < o)
    for date in df.index[shooting_star]:
        patterns.append(
            {
                "pattern": "shooting_star",
                "date": date.isoformat(),
                "direction": "bearish",
                "strength": 2,
            }
        )

    # Morning star (3-candle bullish reversal)
    if len(df) >= 3:
        morning_star = (
            (c.shift(2) < o.shift(2))  # Day 1: bearish
            & (body.shift(1) < body.shift(2) * 0.3)  # Day 2: small body
            & (c > o)  # Day 3: bullish
            & (c > (o.shift(2) + c.shift(2)) / 2)  # Day 3 closes above midpoint of day 1
        )
        for date in df.index[morning_star]:
            patterns.append(
                {
                    "pattern": "morning_star",
                    "date": date.isoformat(),
                    "direction": "bullish",
                    "strength": 3,
                }
            )

    # Evening star (3-candle bearish reversal)
    if len(df) >= 3:
        evening_star = (
            (c.shift(2) > o.shift(2))  # Day 1: bullish
            & (body.shift(1) < body.shift(2) * 0.3)  # Day 2: small body
            & (c < o)  # Day 3: bearish
            & (c < (o.shift(2) + c.shift(2)) / 2)  # Day 3 closes below midpoint of day 1
        )
        for date in df.index[evening_star]:
            patterns.append(
                {
                    "pattern": "evening_star",
                    "date": date.isoformat(),
                    "direction": "bearish",
                    "strength": 3,
                }
            )

    # Three white soldiers
    if len(df) >= 3:
        tws = (
            (c > o)
            & (c.shift(1) > o.shift(1))
            & (c.shift(2) > o.shift(2))
            & (c > c.shift(1))
            & (c.shift(1) > c.shift(2))
            & (o > o.shift(1))
            & (o.shift(1) > o.shift(2))
            & (body > body.shift(1) * 0.5)
        )
        for date in df.index[tws]:
            patterns.append(
                {
                    "pattern": "three_white_soldiers",
                    "date": date.isoformat(),
                    "direction": "bullish",
                    "strength": 3,
                }
            )

    # Three black crows
    if len(df) >= 3:
        tbc = (
            (c < o)
            & (c.shift(1) < o.shift(1))
            & (c.shift(2) < o.shift(2))
            & (c < c.shift(1))
            & (c.shift(1) < c.shift(2))
            & (o < o.shift(1))
            & (o.shift(1) < o.shift(2))
            & (body > body.shift(1) * 0.5)
        )
        for date in df.index[tbc]:
            patterns.append(
                {
                    "pattern": "three_black_crows",
                    "date": date.isoformat(),
                    "direction": "bearish",
                    "strength": 3,
                }
            )

    # Sort by date, most recent first
    patterns.sort(key=lambda x: x["date"], reverse=True)
    return patterns


def detect_support_resistance(df: pd.DataFrame, window: int = 20) -> dict:
    """Detect support and resistance levels using local minima/maxima.

    Returns:
        Dict with support, resistance, and current_price.
    """
    if len(df) < window:
        window = len(df) // 2 or 1

    lows = df["Low"]
    highs = df["High"]

    # Local minima and maxima
    local_min = (lows == lows.rolling(window=window, center=True).min()) & (
        lows.shift(1) > lows
    ) & (lows.shift(-1) > lows)
    local_max = (highs == highs.rolling(window=window, center=True).max()) & (
        highs.shift(1) < highs
    ) & (highs.shift(-1) < highs)

    support_levels = sorted(lows[local_min].dropna().tolist())
    resistance_levels = sorted(highs[local_max].dropna().tolist())

    # Deduplicate nearby levels (within 1%)
    support_levels = _deduplicate_levels(support_levels)
    resistance_levels = _deduplicate_levels(resistance_levels)

    return {
        "support": support_levels[-5:] if support_levels else [],
        "resistance": resistance_levels[-5:] if resistance_levels else [],
        "current_price": round(df["Close"].iloc[-1], 4),
    }


def _deduplicate_levels(levels: list[float], tolerance: float = 0.01) -> list[float]:
    """Remove price levels that are within tolerance % of each other."""
    if not levels:
        return []
    result = [levels[0]]
    for level in levels[1:]:
        if all(abs(level - r) / r > tolerance for r in result):
            result.append(level)
    return result


def generate_signals(df: pd.DataFrame, strategy: str) -> pd.DataFrame:
    """Generate trading signals from a strategy.

    Strategies: sma_crossover, ema_crossover, rsi_mean_reversion,
    macd_momentum, bollinger_breakout.

    Returns:
        DataFrame with Signal column (1=buy, -1=sell, 0=hold).
    """
    result = df.copy()
    result["Signal"] = 0

    if strategy == "sma_crossover":
        fast = result.ta.sma(length=50, append=False)
        slow = result.ta.sma(length=200, append=False)
        result["Signal"] = np.where(fast > slow, 1, np.where(fast < slow, -1, 0))
    elif strategy == "ema_crossover":
        fast = result.ta.ema(length=12, append=False)
        slow = result.ta.ema(length=26, append=False)
        result["Signal"] = np.where(fast > slow, 1, np.where(fast < slow, -1, 0))
    elif strategy == "rsi_mean_reversion":
        rsi = result.ta.rsi(length=14, append=False)
        result["Signal"] = np.where(rsi < 30, 1, np.where(rsi > 70, -1, 0))
    elif strategy == "macd_momentum":
        macd_df = result.ta.macd(append=False)
        if macd_df is not None and not macd_df.empty:
            macd_line = macd_df.iloc[:, 0]
            signal_line = macd_df.iloc[:, 1]
            result["Signal"] = np.where(
                macd_line > signal_line, 1, np.where(macd_line < signal_line, -1, 0)
            )
    elif strategy == "bollinger_breakout":
        bb = result.ta.bbands(length=20, append=False)
        if bb is not None and not bb.empty:
            upper = bb.iloc[:, 2]
            lower = bb.iloc[:, 0]
            result["Signal"] = np.where(
                result["Close"] > upper, 1, np.where(result["Close"] < lower, -1, 0)
            )
    else:
        logger.warning("Unknown strategy: %s", strategy)

    return result


def compute_correlation_matrix(dfs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Compute correlation matrix of closing prices across symbols."""
    closes = {sym: df["Close"] for sym, df in dfs.items()}
    combined = pd.DataFrame(closes)
    return combined.corr().round(4)


def summarize_technicals(df: pd.DataFrame) -> dict:
    """Summarize technical analysis on a DataFrame.

    Returns:
        Dict with trend, momentum, volatility, and volume summaries.
    """
    if len(df) < 50:
        return {"error": "Insufficient data (need >= 50 bars)"}

    close = df["Close"]
    sma20 = df.ta.sma(length=20, append=False)
    sma50 = df.ta.sma(length=50, append=False)
    sma200 = df.ta.sma(length=200, append=False)
    rsi = df.ta.rsi(length=14, append=False)
    macd_df = df.ta.macd(append=False)
    bb = df.ta.bbands(length=20, append=False)
    atr = df.ta.atr(length=14, append=False)
    adx = df.ta.adx(length=14, append=False)

    adx_val = adx.iloc[-1] if adx is not None and not adx.empty else None
    adx_value = adx_val.iloc[-1] if hasattr(adx_val, "iloc") else adx_val  # type: ignore[union-attr]

    return {
        "price": round(close.iloc[-1], 4),
        "trend": {
            "sma20": round(sma20.iloc[-1], 4) if sma20 is not None else None,
            "sma50": round(sma50.iloc[-1], 4) if sma50 is not None else None,
            "sma200": round(sma200.iloc[-1], 4) if sma200 is not None else None,
            "above_sma200": close.iloc[-1] > sma200.iloc[-1] if sma200 is not None else None,
        },
        "momentum": {
            "rsi_14": round(rsi.iloc[-1], 2) if rsi is not None else None,
            "macd_signal": "bullish"
            if macd_df is not None and macd_df.iloc[-1, 0] > macd_df.iloc[-1, 1]
            else "bearish"
            if macd_df is not None
            else None,
        },
        "volatility": {
            "bb_position": round(
                (close.iloc[-1] - bb.iloc[-1, 0]) / (bb.iloc[-1, 2] - bb.iloc[-1, 0]), 4
            )
            if bb is not None and bb.iloc[-1, 2] != bb.iloc[-1, 0]
            else None,
            "atr_14": round(atr.iloc[-1], 4) if atr is not None else None,
            "adx_14": round(adx_value, 2) if adx_value is not None else None,
        },
        "volume": {
            "avg_volume_20": round(df["Volume"].tail(20).mean(), 0),
            "latest_volume": int(df["Volume"].iloc[-1]),
        },
    }

"""Technical analysis tool functions."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd
import pandas_ta  # noqa: F401  # registers the DataFrame .ta accessor

logger = logging.getLogger(__name__)


def _compute_sma(result: pd.DataFrame, spec: str) -> None:
    length = int(spec.split("_")[1])
    result.ta.sma(length=length, append=True)


def _compute_ema(result: pd.DataFrame, spec: str) -> None:
    length = int(spec.split("_")[1])
    result.ta.ema(length=length, append=True)


def _compute_rsi(result: pd.DataFrame, spec: str) -> None:
    length = int(spec.split("_")[1])
    result.ta.rsi(length=length, append=True)


def _compute_macd(result: pd.DataFrame, _spec: str) -> None:
    result.ta.macd(append=True)


def _compute_bbands(result: pd.DataFrame, _spec: str) -> None:
    result.ta.bbands(append=True)


def _compute_atr(result: pd.DataFrame, spec: str) -> None:
    length = int(spec.split("_")[1])
    result.ta.atr(length=length, append=True)


def _compute_adx(result: pd.DataFrame, spec: str) -> None:
    length = int(spec.split("_")[1])
    result.ta.adx(length=length, append=True)


def _compute_obv(result: pd.DataFrame, _spec: str) -> None:
    result.ta.obv(append=True)


def _compute_stoch(result: pd.DataFrame, _spec: str) -> None:
    result.ta.stoch(append=True)


def _compute_vwap(result: pd.DataFrame, _spec: str) -> None:
    result.ta.vwap(append=True)


def _compute_supertrend(result: pd.DataFrame, _spec: str) -> None:
    result.ta.supertrend(append=True)


_INDICATOR_DISPATCH: dict[str, Callable[[pd.DataFrame, str], None]] = {
    "sma_": _compute_sma,
    "ema_": _compute_ema,
    "rsi_": _compute_rsi,
    "macd": _compute_macd,
    "macd_signal": _compute_macd,
    "macd_hist": _compute_macd,
    "bbands_": _compute_bbands,
    "atr_": _compute_atr,
    "adx_": _compute_adx,
    "obv": _compute_obv,
    "stoch_k": _compute_stoch,
    "stoch_d": _compute_stoch,
    "vwap": _compute_vwap,
    "supertrend": _compute_supertrend,
}


def _compute_single_indicator(result: pd.DataFrame, spec: str) -> None:
    """Compute a single indicator, logging failures."""
    try:
        _dispatch_indicator(result, spec)
    except Exception as exc:
        logger.warning("Failed to compute indicator %s: %s", spec, exc)


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
        _compute_single_indicator(result, spec)
    return result


def _dispatch_indicator(result: pd.DataFrame, spec: str) -> None:
    """Look up and execute the handler for a single indicator spec."""
    for prefix, handler in _INDICATOR_DISPATCH.items():
        if spec.startswith(prefix):
            handler(result, spec)
            return
    logger.warning("Unknown indicator: %s", spec)


# ---------------------------------------------------------------------------
# Pattern detection
# ---------------------------------------------------------------------------

def _detect_doji(
    df: pd.DataFrame,
    body: pd.Series,
    range_: pd.Series,
) -> list[dict]:
    mask = body < (range_ * 0.05)
    return [
        {"pattern": "doji", "date": d.isoformat(), "direction": "neutral", "strength": 1}
        for d in df.index[mask]
    ]


def _detect_engulfing(
    df: pd.DataFrame,
    o: pd.Series,
    c: pd.Series,
) -> list[dict]:
    bullish = (
        (o.shift(1) > c.shift(1))
        & (o < c)
        & (o <= c.shift(1))
        & (c >= o.shift(1))
    )
    bearish = (
        (o.shift(1) < c.shift(1))
        & (o > c)
        & (o >= c.shift(1))
        & (c <= o.shift(1))
    )
    patterns: list[dict] = []
    for d in df.index[bullish]:
        patterns.append(
            {
                "pattern": "engulfing",
                "date": d.isoformat(),
                "direction": "bullish",
                "strength": 2,
            }
        )
    for d in df.index[bearish]:
        patterns.append(
            {
                "pattern": "engulfing",
                "date": d.isoformat(),
                "direction": "bearish",
                "strength": 2,
            }
        )
    return patterns


def _detect_hammer(
    df: pd.DataFrame,
    o: pd.Series,
    c: pd.Series,
    upper_shadow: pd.Series,
    lower_shadow: pd.Series,
    body: pd.Series,
) -> list[dict]:
    mask = (lower_shadow > body * 2) & (upper_shadow < body * 0.5) & (c > o)
    return [
        {
            "pattern": "hammer",
            "date": d.isoformat(),
            "direction": "bullish",
            "strength": 2,
        }
        for d in df.index[mask]
    ]


def _detect_shooting_star(
    df: pd.DataFrame,
    o: pd.Series,
    c: pd.Series,
    upper_shadow: pd.Series,
    lower_shadow: pd.Series,
    body: pd.Series,
) -> list[dict]:
    mask = (upper_shadow > body * 2) & (lower_shadow < body * 0.5) & (c < o)
    return [
        {
            "pattern": "shooting_star",
            "date": d.isoformat(),
            "direction": "bearish",
            "strength": 2,
        }
        for d in df.index[mask]
    ]


def _detect_morning_star(
    df: pd.DataFrame,
    o: pd.Series,
    c: pd.Series,
    body: pd.Series,
) -> list[dict]:
    mask = (
        (c.shift(2) < o.shift(2))
        & (body.shift(1) < body.shift(2) * 0.3)
        & (c > o)
        & (c > (o.shift(2) + c.shift(2)) / 2)
    )
    return [
        {
            "pattern": "morning_star",
            "date": d.isoformat(),
            "direction": "bullish",
            "strength": 3,
        }
        for d in df.index[mask]
    ]


def _detect_evening_star(
    df: pd.DataFrame,
    o: pd.Series,
    c: pd.Series,
    body: pd.Series,
) -> list[dict]:
    mask = (
        (c.shift(2) > o.shift(2))
        & (body.shift(1) < body.shift(2) * 0.3)
        & (c < o)
        & (c < (o.shift(2) + c.shift(2)) / 2)
    )
    return [
        {
            "pattern": "evening_star",
            "date": d.isoformat(),
            "direction": "bearish",
            "strength": 3,
        }
        for d in df.index[mask]
    ]


def _detect_three_white_soldiers(
    df: pd.DataFrame,
    o: pd.Series,
    c: pd.Series,
    body: pd.Series,
) -> list[dict]:
    mask = (
        (c > o)
        & (c.shift(1) > o.shift(1))
        & (c.shift(2) > o.shift(2))
        & (c > c.shift(1))
        & (c.shift(1) > c.shift(2))
        & (o > o.shift(1))
        & (o.shift(1) > o.shift(2))
        & (body > body.shift(1) * 0.5)
    )
    return [
        {
            "pattern": "three_white_soldiers",
            "date": d.isoformat(),
            "direction": "bullish",
            "strength": 3,
        }
        for d in df.index[mask]
    ]


def _detect_three_black_crows(
    df: pd.DataFrame,
    o: pd.Series,
    c: pd.Series,
    body: pd.Series,
) -> list[dict]:
    mask = (
        (c < o)
        & (c.shift(1) < o.shift(1))
        & (c.shift(2) < o.shift(2))
        & (c < c.shift(1))
        & (c.shift(1) < c.shift(2))
        & (o < o.shift(1))
        & (o.shift(1) < o.shift(2))
        & (body > body.shift(1) * 0.5)
    )
    return [
        {
            "pattern": "three_black_crows",
            "date": d.isoformat(),
            "direction": "bearish",
            "strength": 3,
        }
        for d in df.index[mask]
    ]


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

    patterns.extend(_detect_doji(df, body, range_))
    patterns.extend(_detect_engulfing(df, o, c))
    patterns.extend(_detect_hammer(df, o, c, upper_shadow, lower_shadow, body))
    patterns.extend(_detect_shooting_star(df, o, c, upper_shadow, lower_shadow, body))
    patterns.extend(_detect_morning_star(df, o, c, body))
    patterns.extend(_detect_evening_star(df, o, c, body))
    patterns.extend(_detect_three_white_soldiers(df, o, c, body))
    patterns.extend(_detect_three_black_crows(df, o, c, body))

    patterns.sort(key=lambda x: x["date"], reverse=True)
    return patterns


# ---------------------------------------------------------------------------
# Support / Resistance
# ---------------------------------------------------------------------------

def detect_support_resistance(df: pd.DataFrame, window: int = 20) -> dict:
    """Detect support and resistance levels using local minima/maxima.

    Returns:
        Dict with support, resistance, and current_price.
    """
    if len(df) < window:
        window = len(df) // 2 or 1

    lows = df["Low"]
    highs = df["High"]

    local_min = (lows == lows.rolling(window=window, center=True).min()) & (
        lows.shift(1) > lows
    ) & (lows.shift(-1) > lows)
    local_max = (highs == highs.rolling(window=window, center=True).max()) & (
        highs.shift(1) < highs
    ) & (highs.shift(-1) < highs)

    support_levels = sorted(lows[local_min].dropna().tolist())
    resistance_levels = sorted(highs[local_max].dropna().tolist())

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


def wilder_rsi(close: pd.Series, length: int = 14) -> float | None:
    """Latest Wilder-smoothed RSI value from a close series.

    Returns:
        RSI in [0, 100], or None with insufficient data.
    """
    if len(close) < length + 1:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / length, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / length, adjust=False).mean()
    last_loss = float(loss.iloc[-1])
    if last_loss == 0:
        return 100.0
    rs = float(gain.iloc[-1]) / last_loss
    return round(100 - 100 / (1 + rs), 4)


# ---------------------------------------------------------------------------
# Signal generation
# ---------------------------------------------------------------------------

def _signal_sma_crossover(result: pd.DataFrame) -> pd.DataFrame:
    fast = result.ta.sma(length=50, append=False)
    slow = result.ta.sma(length=200, append=False)
    result["Signal"] = np.where(fast > slow, 1, np.where(fast < slow, -1, 0))
    return result


def _signal_ema_crossover(result: pd.DataFrame) -> pd.DataFrame:
    fast = result.ta.ema(length=12, append=False)
    slow = result.ta.ema(length=26, append=False)
    result["Signal"] = np.where(fast > slow, 1, np.where(fast < slow, -1, 0))
    return result


def _signal_rsi_mean_reversion(result: pd.DataFrame) -> pd.DataFrame:
    rsi = result.ta.rsi(length=14, append=False)
    result["Signal"] = np.where(rsi < 30, 1, np.where(rsi > 70, -1, 0))
    return result


def _signal_macd_momentum(result: pd.DataFrame) -> pd.DataFrame:
    macd_df = result.ta.macd(append=False)
    if macd_df is not None and not macd_df.empty:
        macd_line = macd_df.iloc[:, 0]
        signal_line = macd_df.iloc[:, 1]
        result["Signal"] = np.where(
            macd_line > signal_line, 1, np.where(macd_line < signal_line, -1, 0)
        )
    return result


def _signal_bollinger_breakout(result: pd.DataFrame) -> pd.DataFrame:
    bb = result.ta.bbands(length=20, append=False)
    if bb is not None and not bb.empty:
        upper = bb.iloc[:, 2]
        lower = bb.iloc[:, 0]
        result["Signal"] = np.where(
            result["Close"] > upper, 1, np.where(result["Close"] < lower, -1, 0)
        )
    return result


def _signal_buy_and_hold(result: pd.DataFrame) -> pd.DataFrame:
    if not result.empty:
        result.loc[result.index[0], "Signal"] = 1
    return result


_STRATEGY_DISPATCH: dict[str, Callable[[pd.DataFrame], pd.DataFrame]] = {
    "sma_crossover": _signal_sma_crossover,
    "ema_crossover": _signal_ema_crossover,
    "rsi_mean_reversion": _signal_rsi_mean_reversion,
    "macd_momentum": _signal_macd_momentum,
    "bollinger_breakout": _signal_bollinger_breakout,
    "buy_and_hold": _signal_buy_and_hold,
}


def generate_signals(df: pd.DataFrame, strategy: str) -> pd.DataFrame:
    """Generate trading signals from a strategy.

    Strategies: sma_crossover, ema_crossover, rsi_mean_reversion,
    macd_momentum, bollinger_breakout, buy_and_hold.

    Returns:
        DataFrame with Signal column (1=buy, -1=sell, 0=hold).
    """
    result = df.copy()
    result["Signal"] = 0

    handler = _STRATEGY_DISPATCH.get(strategy)
    if handler is None:
        logger.warning("Unknown strategy: %s", strategy)
        return result

    return handler(result)


# ---------------------------------------------------------------------------
# Correlation matrix
# ---------------------------------------------------------------------------

def compute_correlation_matrix(dfs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Compute correlation matrix of closing prices across symbols."""
    closes = {sym: df["Close"] for sym, df in dfs.items()}
    combined = pd.DataFrame(closes)
    return combined.corr().round(4)


# ---------------------------------------------------------------------------
# Technical summary
# ---------------------------------------------------------------------------

def _summarize_trend(
    close: pd.Series,
    sma20: pd.Series | None,
    sma50: pd.Series | None,
    sma200: pd.Series | None,
) -> dict:
    return {
        "sma20": round(sma20.iloc[-1], 4) if sma20 is not None else None,
        "sma50": round(sma50.iloc[-1], 4) if sma50 is not None else None,
        "sma200": round(sma200.iloc[-1], 4) if sma200 is not None else None,
        "above_sma200": (
            close.iloc[-1] > sma200.iloc[-1] if sma200 is not None else None
        ),
    }


def _summarize_momentum(
    rsi: pd.Series | None, macd_df: pd.DataFrame | None
) -> dict:
    macd_signal = None
    if macd_df is not None:
        macd_signal = (
            "bullish"
            if macd_df.iloc[-1, 0] > macd_df.iloc[-1, 1]  # type: ignore[operator, call-overload]
            else "bearish"
        )
    return {
        "rsi_14": round(rsi.iloc[-1], 2) if rsi is not None else None,
        "macd_signal": macd_signal,
    }


def _summarize_volatility(
    close: pd.Series,
    bb: pd.DataFrame | None,
    atr: pd.Series | None,
    adx_value: float | None,
) -> dict:
    bb_position = None
    if bb is not None and bb.iloc[-1, 2] != bb.iloc[-1, 0]:
        bb_position = round(
            (close.iloc[-1] - bb.iloc[-1, 0]) / (bb.iloc[-1, 2] - bb.iloc[-1, 0]),  # type: ignore[operator, call-overload, arg-type]
            4,
        )
    return {
        "bb_position": bb_position,
        "atr_14": round(atr.iloc[-1], 4) if atr is not None else None,
        "adx_14": round(adx_value, 2) if adx_value is not None else None,
    }


def _summarize_volume(df: pd.DataFrame) -> dict:
    return {
        "avg_volume_20": round(df["Volume"].tail(20).mean(), 0),
        "latest_volume": int(df["Volume"].iloc[-1]),
    }


def _extract_adx_value(adx: Any) -> Any:
    """Extract the latest scalar ADX value from the ADX DataFrame."""
    if adx is None or adx.empty:
        return None
    adx_val = adx.iloc[-1]
    return adx_val.iloc[-1] if hasattr(adx_val, "iloc") else adx_val


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

    return {
        "price": round(close.iloc[-1], 4),
        "trend": _summarize_trend(close, sma20, sma50, sma200),
        "momentum": _summarize_momentum(rsi, macd_df),
        "volatility": _summarize_volatility(close, bb, atr, _extract_adx_value(df.ta.adx(length=14, append=False))),
        "volume": _summarize_volume(df),
    }

"""Pair trading / statistical arbitrage tool functions.

Finds cointegrated pairs (Engle-Granger) within a universe or sector
and computes tradeable spread metrics: OLS hedge ratio, spread z-score,
and mean-reversion half-life. Correlation is a cheap pre-filter only —
cointegration, not correlation, is what makes a spread tradeable.
"""
from __future__ import annotations

import asyncio
import logging
import math
from itertools import combinations

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import coint  # type: ignore[import-untyped]

from quantagent.tools.providers.base import AbstractDataProvider
from quantagent.tools.sector_analysis import classify_symbols

logger = logging.getLogger(__name__)

_MIN_OBSERVATIONS = 120


def _hedge_ratio(a: pd.Series, b: pd.Series) -> float:
    """OLS slope of a on b (units of b per unit of a's spread)."""
    slope, _ = np.polyfit(b.to_numpy(), a.to_numpy(), 1)
    return float(slope)


def _spread(a: pd.Series, b: pd.Series, hedge_ratio: float) -> pd.Series:
    return a - hedge_ratio * b


def _zscore(spread: pd.Series) -> float | None:
    std = float(spread.std())
    if std == 0 or math.isnan(std):
        return None
    return round((float(spread.iloc[-1]) - float(spread.mean())) / std, 4)


def _half_life(spread: pd.Series) -> float | None:
    """Mean-reversion half-life in days from an AR(1) fit of the spread.

    Returns None when the spread is not mean-reverting (lambda >= 0).
    """
    lagged = spread.shift(1).iloc[1:]
    delta = spread.diff().iloc[1:]
    if len(lagged) < 20:
        return None
    lam, _ = np.polyfit(lagged.to_numpy(), delta.to_numpy(), 1)
    if lam >= 0:
        return None
    return round(float(-math.log(2) / lam), 2)


def _pair_metrics(a: pd.Series, b: pd.Series) -> dict | None:
    """Full metrics for one aligned pair, or None when degenerate."""
    ratio = _hedge_ratio(a, b)
    spread = _spread(a, b, ratio)
    zscore = _zscore(spread)
    if zscore is None:
        return None
    _, pvalue, _ = coint(a.to_numpy(), b.to_numpy())
    return {
        "correlation": round(float(a.corr(b)), 4),
        "coint_pvalue": round(float(pvalue), 4),
        "hedge_ratio": round(ratio, 4),
        "half_life_days": _half_life(spread),
        "current_zscore": zscore,
        "spread_mean": round(float(spread.mean()), 4),
        "spread_std": round(float(spread.std()), 4),
    }


def _close_matrix(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Aligned close matrix, dropping symbols with short history."""
    closes = {
        sym: df["Close"]
        for sym, df in frames.items()
        if len(df) >= _MIN_OBSERVATIONS
    }
    if not closes:
        return pd.DataFrame()
    return pd.DataFrame(closes).dropna()


def _scan_pairs(
    matrix: pd.DataFrame, pvalue_threshold: float, min_correlation: float
) -> list[dict]:
    """Test all pairs; correlation gate first, cointegration on survivors."""
    columns = list(matrix.columns)
    corr = matrix.corr().to_numpy()
    rows = []
    for i, j in combinations(range(len(columns)), 2):
        if corr[i, j] < min_correlation:
            continue
        sym_a, sym_b = columns[i], columns[j]
        metrics = _pair_metrics(matrix[sym_a], matrix[sym_b])
        if metrics is None or metrics["coint_pvalue"] > pvalue_threshold:
            continue
        rows.append({"symbol_a": sym_a, "symbol_b": sym_b, **metrics})
    return rows


async def _resolve_symbols(
    provider: AbstractDataProvider,
    universe: str,
    sector: str | None,
    max_symbols: int,
) -> list[str]:
    from quantagent.tools.screener import _fetch_universe_tickers

    symbols = _fetch_universe_tickers(universe)
    if sector is not None:
        classifications = await classify_symbols(provider, symbols)
        symbols = [
            s for s in symbols
            if (classifications.get(s, {}).get("sector") or "").lower() == sector.lower()
        ]
    return symbols[:max_symbols]


async def find_cointegrated_pairs(
    provider: AbstractDataProvider,
    universe: str = "sp500",
    sector: str | None = None,
    max_symbols: int = 60,
    pvalue_threshold: float = 0.05,
    min_correlation: float = 0.7,
    limit: int = 20,
) -> pd.DataFrame:
    """Find cointegrated stock pairs for statistical arbitrage.

    Pairs are pre-filtered by correlation (cheap) before the
    Engle-Granger cointegration test (expensive). Restricting to one
    sector is strongly recommended — cross-sector pairs cointegrate by
    accident far more often than by economics.

    Args:
        provider: Market data provider.
        universe: Universe to scan.
        sector: Optional sector filter (classification is cached).
        max_symbols: Cap on symbols scanned (O(n^2) pairs).
        pvalue_threshold: Maximum Engle-Granger p-value.
        min_correlation: Correlation pre-filter gate.
        limit: Maximum pairs returned.

    Returns:
        DataFrame with columns: symbol_a, symbol_b, correlation,
        coint_pvalue, hedge_ratio, half_life_days, current_zscore,
        spread_mean, spread_std. Sorted by p-value.
    """
    symbols = await _resolve_symbols(provider, universe, sector, max_symbols)
    if len(symbols) < 2:
        return pd.DataFrame()
    frames = await provider.get_batch_ohlcv(symbols, period="1y")
    matrix = _close_matrix(frames)
    if matrix.empty or len(matrix.columns) < 2:
        return pd.DataFrame()
    rows = await asyncio.to_thread(
        _scan_pairs, matrix, pvalue_threshold, min_correlation
    )
    if not rows:
        return pd.DataFrame()
    result = pd.DataFrame(rows).sort_values("coint_pvalue")
    return result.head(limit).reset_index(drop=True)


async def compute_spread_metrics(
    provider: AbstractDataProvider,
    symbol_a: str,
    symbol_b: str,
    period: str = "1y",
) -> dict:
    """Compute tradeable spread metrics for a candidate pair.

    Args:
        provider: Market data provider.
        symbol_a: First leg (spread = a - hedge_ratio * b).
        symbol_b: Second leg.
        period: History window.

    Returns:
        Dict: {symbol_a, symbol_b, hedge_ratio, coint_pvalue,
        correlation, current_zscore, spread_mean, spread_std,
        half_life_days, signal}. Signal: |z| >= 2 entry-zone (with the
        long/short legs stated), |z| <= 0.5 exit-zone, else neutral.

    Raises:
        ValueError: When there is insufficient overlapping history.
    """
    symbol_a, symbol_b = symbol_a.upper(), symbol_b.upper()
    frames = await provider.get_batch_ohlcv([symbol_a, symbol_b], period=period)
    matrix = _close_matrix(frames)
    if set(matrix.columns) != {symbol_a, symbol_b}:
        raise ValueError(
            f"Insufficient overlapping history for {symbol_a}/{symbol_b} "
            f"(need >= {_MIN_OBSERVATIONS} aligned sessions)"
        )
    metrics = _pair_metrics(matrix[symbol_a], matrix[symbol_b])
    if metrics is None:
        raise ValueError(f"Degenerate spread for {symbol_a}/{symbol_b}")
    return {
        "symbol_a": symbol_a,
        "symbol_b": symbol_b,
        **metrics,
        "signal": _spread_signal(metrics["current_zscore"], symbol_a, symbol_b),
    }


def _spread_signal(zscore: float, symbol_a: str, symbol_b: str) -> str:
    if zscore >= 2:
        return f"entry-zone: spread rich — short {symbol_a}, long {symbol_b}"
    if zscore <= -2:
        return f"entry-zone: spread cheap — long {symbol_a}, short {symbol_b}"
    if abs(zscore) <= 0.5:
        return "exit-zone: spread near its mean"
    return "neutral"

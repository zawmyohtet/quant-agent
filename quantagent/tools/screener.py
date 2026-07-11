"""Stock screener tool functions.

Fundamental screening fetches quotes/fundamentals per symbol (bounded
concurrency). Technical and pattern screens batch-download OHLCV for
the whole universe and evaluate locally.

Note: piotroski_f screening is intentionally not offered — current
providers don't supply the balance-sheet fields the F-Score needs, so
it would silently score 0. It can return with a richer fundamentals
provider (FMP).
"""
from __future__ import annotations

import asyncio
import logging
import operator as op_module
from collections.abc import Callable
from typing import Any

import pandas as pd

from quantagent.tools.providers.base import AbstractDataProvider
from quantagent.tools.technical import wilder_rsi
from quantagent.tools.universe import load_universe

logger = logging.getLogger(__name__)


def _fetch_universe_tickers(universe: str) -> list[str]:
    """Resolve a universe to tickers, returning [] on failure."""
    try:
        return load_universe(universe)
    except Exception as exc:
        logger.warning("Failed to load universe %s: %s", universe, exc)
        return []


async def _build_screening_row(
    provider: AbstractDataProvider, ticker: str
) -> dict | None:
    """Fetch fundamentals + quote for a single ticker, or None on failure."""
    try:
        fundamentals = await provider.get_fundamentals(ticker)
        quote = await provider.get_quote(ticker)
        return {
            "symbol": ticker,
            "name": fundamentals.get("name", ""),
            "pe_ratio": fundamentals.get("pe_ratio"),
            "pb_ratio": fundamentals.get("pb_ratio"),
            "roe": fundamentals.get("roe"),
            "roa": fundamentals.get("roa"),
            "debt_equity": fundamentals.get("debt_equity"),
            "market_cap": quote.get("market_cap"),
            "volume": quote.get("volume"),
            "dividend_yield": fundamentals.get("dividend_yield"),
            "revenue_growth": fundamentals.get("revenue_growth"),
            "eps_growth": fundamentals.get("eps_growth"),
            "beta": fundamentals.get("beta"),
            "price": quote.get("price"),
        }
    except Exception as exc:
        logger.debug("Skipping %s: %s", ticker, exc)
        return None


async def _fetch_screening_rows(
    provider: AbstractDataProvider, tickers: list[str]
) -> list[dict]:
    """Build screening rows for all tickers with bounded concurrency."""
    semaphore = asyncio.Semaphore(8)

    async def _bounded(ticker: str) -> dict | None:
        async with semaphore:
            return await _build_screening_row(provider, ticker)

    results = await asyncio.gather(*(_bounded(t) for t in tickers))
    return [row for row in results if row is not None]


async def screen_stocks(
    provider: AbstractDataProvider,
    universe: str = "sp500",
    criteria: dict | None = None,
    sort_by: str = "market_cap",
    ascending: bool = False,
    limit: int = 20,
    max_symbols: int | None = None,
) -> pd.DataFrame:
    """Screen stocks by fundamental criteria.

    Supported criteria keys: pe_lt/gt, pb_lt/gt, roe_gt, roa_gt,
    debt_equity_lt, mcap_gt/lt (aliases market_cap_gt/lt), volume_gt,
    dividend_yield_gt, revenue_growth_gt, eps_growth_gt, beta_lt.

    Args:
        provider: Market data provider.
        universe: Universe to screen.
        criteria: Filter criteria (see keys above).
        sort_by: Column to sort by.
        ascending: Sort direction.
        limit: Maximum rows returned.
        max_symbols: Optional cap on symbols fetched (default: whole universe).
    """
    criteria = criteria or {}
    tickers = _fetch_universe_tickers(universe)
    if not tickers:
        logger.warning("No tickers found for universe: %s", universe)
        return pd.DataFrame()
    if max_symbols is not None:
        tickers = tickers[:max_symbols]
    rows = await _fetch_screening_rows(provider, tickers)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = _apply_criteria(df, criteria)

    if sort_by in df.columns:
        df = df.sort_values(by=sort_by, ascending=ascending, na_position="last")

    return df.head(limit).reset_index(drop=True)


async def screen_by_fundamentals(
    provider: AbstractDataProvider,
    criteria: dict[str, Any],
    universe: str = "sp500",
    limit: int = 50,
) -> pd.DataFrame:
    """Screen by fundamental criteria (alias of screen_stocks with a
    larger default result set).

    Args:
        provider: Market data provider.
        criteria: Fundamental criteria (see screen_stocks).
        universe: Universe to screen.
        limit: Maximum rows returned.
    """
    return await screen_stocks(
        provider, universe=universe, criteria=criteria, limit=limit
    )


_CRITERIA_DISPATCH: dict[str, tuple[str, Callable[[Any, Any], bool]]] = {
    "pe_lt": ("pe_ratio", op_module.lt),
    "pe_gt": ("pe_ratio", op_module.gt),
    "pb_lt": ("pb_ratio", op_module.lt),
    "pb_gt": ("pb_ratio", op_module.gt),
    "roe_gt": ("roe", op_module.gt),
    "roa_gt": ("roa", op_module.gt),
    "debt_equity_lt": ("debt_equity", op_module.lt),
    "mcap_gt": ("market_cap", op_module.gt),
    "mcap_lt": ("market_cap", op_module.lt),
    "market_cap_gt": ("market_cap", op_module.gt),
    "market_cap_lt": ("market_cap", op_module.lt),
    "volume_gt": ("volume", op_module.gt),
    "dividend_yield_gt": ("dividend_yield", op_module.gt),
    "revenue_growth_gt": ("revenue_growth", op_module.gt),
    "eps_growth_gt": ("eps_growth", op_module.gt),
    "beta_lt": ("beta", op_module.lt),
}


def _apply_single_criterion(df: pd.DataFrame, key: str, value: Any) -> pd.DataFrame:
    """Apply a single criterion filter, returning the filtered DataFrame."""
    try:
        column, oper = _CRITERIA_DISPATCH.get(key, (None, None))
        if column is None:
            logger.warning("Unknown criteria key: %s", key)
            return df
        return df[oper(df[column], value)]  # type: ignore[return-value, misc]
    except Exception as exc:
        logger.warning("Failed to apply criteria %s: %s", key, exc)
        return df


def _apply_criteria(df: pd.DataFrame, criteria: dict[str, Any]) -> pd.DataFrame:
    """Apply screening criteria filters to a DataFrame."""
    for key, value in criteria.items():
        df = _apply_single_criterion(df, key, value)
    return df


# ── Technical screening ──────────────────────────────────────────────────────


def _sma(close: pd.Series, period: int) -> float | None:
    if len(close) < period:
        return None
    return float(close.iloc[-period:].mean())


def _macd_bullish(close: pd.Series) -> bool | None:
    if len(close) < 35:
        return None
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    return bool(macd_line.iloc[-1] > signal_line.iloc[-1])


def _volume_ratio(volume: pd.Series) -> float | None:
    if len(volume) < 21:
        return None
    avg = float(volume.iloc[-21:-1].mean())
    return float(volume.iloc[-1]) / avg if avg > 0 else None


def _above_upper_band(close: pd.Series) -> bool | None:
    if len(close) < 20:
        return None
    window = close.iloc[-20:]
    upper = float(window.mean() + 2 * window.std())
    return bool(float(close.iloc[-1]) > upper)


def _adx(df: pd.DataFrame) -> float | None:
    from quantagent.tools.technical import compute_indicators

    if len(df) < 30:
        return None
    with_adx = compute_indicators(df, ["adx_14"])
    col = next((c for c in with_adx.columns if c.startswith("ADX")), None)
    if col is None or pd.isna(with_adx[col].iloc[-1]):
        return None
    return float(with_adx[col].iloc[-1])


def _check_price_vs_sma(close: pd.Series, period: int, above: bool) -> bool | None:
    sma = _sma(close, int(period))
    if sma is None:
        return None
    is_above = float(close.iloc[-1]) > sma
    return is_above if above else not is_above


def _check_technical(df: pd.DataFrame, key: str, value: Any) -> bool | None:
    """Evaluate one technical criterion; None = not enough data."""
    close, volume = df["Close"], df["Volume"]
    if key in ("rsi_lt", "rsi_gt"):
        rsi = wilder_rsi(close)
        if rsi is None:
            return None
        return bool(rsi < value) if key == "rsi_lt" else bool(rsi > value)
    if key == "macd_bullish":
        bullish = _macd_bullish(close)
        return None if bullish is None else bullish == bool(value)
    if key == "price_above_sma":
        return _check_price_vs_sma(close, value, above=True)
    if key == "price_below_sma":
        return _check_price_vs_sma(close, value, above=False)
    if key == "volume_expansion":
        ratio = _volume_ratio(volume)
        return None if ratio is None else ratio >= value
    if key == "atr_breakout":
        breakout = _above_upper_band(close)
        return None if breakout is None else breakout == bool(value)
    if key == "adx_gt":
        adx = _adx(df)
        return None if adx is None else adx > value
    logger.warning("Unknown technical criteria key: %s", key)
    return True


async def screen_by_technicals(
    provider: AbstractDataProvider,
    criteria: dict[str, Any],
    universe: str = "sp500",
    symbols: list[str] | None = None,
    limit: int = 50,
) -> pd.DataFrame:
    """Screen by technical criteria computed from 1y daily OHLCV.

    Supported criteria keys: rsi_lt/rsi_gt (float), macd_bullish (bool),
    price_above_sma / price_below_sma (period int), volume_expansion
    (min ratio vs 20d avg), atr_breakout (bool: close above upper
    Bollinger band), adx_gt (float).

    Args:
        provider: Market data provider.
        criteria: Technical criteria (see keys above).
        universe: Universe to screen (ignored when symbols given).
        symbols: Explicit symbol list (e.g. pre-filtered by fundamentals).
        limit: Maximum rows returned.

    Returns:
        DataFrame with columns: symbol, price, rsi, volume_ratio.
    """
    tickers = symbols if symbols is not None else _fetch_universe_tickers(universe)
    if not tickers:
        return pd.DataFrame()
    frames = await provider.get_batch_ohlcv(tickers, period="1y")
    rows = []
    for sym, df in frames.items():
        if df.empty:
            continue
        checks = [_check_technical(df, k, v) for k, v in criteria.items()]
        if all(c is True for c in checks):
            rows.append(_technical_row(sym, df))
    return pd.DataFrame(rows).head(limit)


def _technical_row(symbol: str, df: pd.DataFrame) -> dict:
    close, volume = df["Close"], df["Volume"]
    rsi = wilder_rsi(close)
    ratio = _volume_ratio(volume)
    return {
        "symbol": symbol,
        "price": round(float(close.iloc[-1]), 4),
        "rsi": round(rsi, 2) if rsi is not None else None,
        "volume_ratio": round(ratio, 4) if ratio is not None else None,
    }


async def screen_combined(
    provider: AbstractDataProvider,
    technical_criteria: dict[str, Any] | None = None,
    fundamental_criteria: dict[str, Any] | None = None,
    universe: str = "sp500",
    limit: int = 50,
) -> pd.DataFrame:
    """Screen by combined fundamental + technical criteria.

    Applies cheap fundamental filters first, then computes technicals
    only on the survivors, and returns the intersection.

    Args:
        provider: Market data provider.
        technical_criteria: Technical criteria (see screen_by_technicals).
        fundamental_criteria: Fundamental criteria (see screen_stocks).
        universe: Universe to screen.
        limit: Maximum rows returned.
    """
    symbols: list[str] | None = None
    fund_df: pd.DataFrame | None = None
    if fundamental_criteria:
        fund_df = await screen_stocks(
            provider, universe=universe, criteria=fundamental_criteria, limit=10_000
        )
        if fund_df.empty:
            return pd.DataFrame()
        symbols = fund_df["symbol"].tolist()
    if not technical_criteria:
        return fund_df.head(limit) if fund_df is not None else pd.DataFrame()
    tech_df = await screen_by_technicals(
        provider, technical_criteria, universe=universe, symbols=symbols, limit=10_000
    )
    if fund_df is None or tech_df.empty:
        return tech_df.head(limit)
    merged = fund_df.merge(tech_df[["symbol", "rsi", "volume_ratio"]], on="symbol")
    return merged.head(limit).reset_index(drop=True)


# ── Pattern screens ──────────────────────────────────────────────────────────


async def _universe_frames(
    provider: AbstractDataProvider, universe: str
) -> dict[str, pd.DataFrame]:
    tickers = _fetch_universe_tickers(universe)
    if not tickers:
        return {}
    return await provider.get_batch_ohlcv(tickers, period="1y")


def _vcp_metrics(
    df: pd.DataFrame, max_contraction_pct: float, min_prior_advance_pct: float
) -> dict | None:
    """Evaluate Minervini VCP conditions on one symbol's 1y history."""
    close, volume = df["Close"], df["Volume"]
    if len(close) < 200:
        return None
    base, recent = close.iloc[:-63], close.iloc[-63:]
    prior_advance = float(base.max() / base.min() - 1)
    contraction = float(1 - recent.iloc[-1] / recent.max())
    sma200 = _sma(close, 200)
    vol_dryup = float(volume.iloc[-10:].mean() / volume.iloc[-60:].mean())
    tightening = float(
        recent.pct_change().iloc[-10:].std()
        / max(recent.pct_change().std(), 1e-9)
    )
    passed = (
        prior_advance >= min_prior_advance_pct
        and 0 <= contraction <= max_contraction_pct
        and sma200 is not None
        and float(close.iloc[-1]) > sma200
        and vol_dryup < 1.0
        and tightening < 1.0
    )
    if not passed:
        return None
    return {
        "price": round(float(close.iloc[-1]), 4),
        "prior_advance_pct": round(prior_advance, 4),
        "contraction_pct": round(contraction, 4),
        "volume_dryup_ratio": round(vol_dryup, 4),
        "tightening_ratio": round(tightening, 4),
    }


async def screen_vcp_pattern(
    provider: AbstractDataProvider,
    universe: str = "sp500",
    max_contraction_pct: float = 0.50,
    min_prior_advance_pct: float = 0.30,
    limit: int = 50,
) -> pd.DataFrame:
    """Screen for Volatility Contraction Patterns (Minervini).

    Conditions: prior advance above ``min_prior_advance_pct`` (first ~9
    months), current contraction shallower than ``max_contraction_pct``,
    price above the 200-day SMA, 10d/60d volume dry-up, and tightening
    price action (recent volatility below the 3-month norm).

    Args:
        provider: Market data provider.
        universe: Universe to screen.
        max_contraction_pct: Maximum pullback from the recent high.
        min_prior_advance_pct: Minimum prior uptrend size.
        limit: Maximum rows returned.
    """
    frames = await _universe_frames(provider, universe)
    rows = []
    for sym, df in frames.items():
        metrics = _vcp_metrics(df, max_contraction_pct, min_prior_advance_pct)
        if metrics is not None:
            rows.append({"symbol": sym, **metrics})
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values("contraction_pct").head(limit).reset_index(drop=True)


async def screen_breakout_candidates(
    provider: AbstractDataProvider,
    universe: str = "sp500",
    proximity_to_high_pct: float = 0.05,
    volume_ratio_min: float = 1.5,
    limit: int = 50,
) -> pd.DataFrame:
    """Screen for stocks near 52-week highs with volume expansion.

    Args:
        provider: Market data provider.
        universe: Universe to screen.
        proximity_to_high_pct: Maximum distance below the 52-week high.
        volume_ratio_min: Minimum last-day volume vs 20d average.
        limit: Maximum rows returned.

    Returns:
        DataFrame with columns: symbol, price, pct_from_high, volume_ratio.
    """
    frames = await _universe_frames(provider, universe)
    rows = []
    for sym, df in frames.items():
        close, volume = df["Close"], df["Volume"]
        if len(close) < 30:
            continue
        pct_from_high = float(1 - close.iloc[-1] / close.max())
        ratio = _volume_ratio(volume)
        if pct_from_high <= proximity_to_high_pct and ratio and ratio >= volume_ratio_min:
            rows.append(
                {
                    "symbol": sym,
                    "price": round(float(close.iloc[-1]), 4),
                    "pct_from_high": round(pct_from_high, 4),
                    "volume_ratio": round(ratio, 4),
                }
            )
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values("volume_ratio", ascending=False).head(limit).reset_index(drop=True)


async def screen_oversold_reversal(
    provider: AbstractDataProvider,
    universe: str = "sp500",
    rsi_threshold: float = 30.0,
    min_decline_pct: float = 0.20,
    limit: int = 50,
) -> pd.DataFrame:
    """Screen for oversold reversal candidates.

    Conditions: RSI below ``rsi_threshold``, price down more than
    ``min_decline_pct`` from its 6-month high, and a reversal bar (last
    close up on the day, closing in the upper half of its range).

    Args:
        provider: Market data provider.
        universe: Universe to screen.
        rsi_threshold: Maximum RSI-14.
        min_decline_pct: Minimum decline from the 6-month high.
        limit: Maximum rows returned.

    Returns:
        DataFrame with columns: symbol, price, rsi, decline_pct.
    """
    frames = await _universe_frames(provider, universe)
    rows = []
    for sym, df in frames.items():
        row = _oversold_row(sym, df, rsi_threshold, min_decline_pct)
        if row is not None:
            rows.append(row)
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values("rsi").head(limit).reset_index(drop=True)


def _oversold_row(
    symbol: str, df: pd.DataFrame, rsi_threshold: float, min_decline_pct: float
) -> dict | None:
    close = df["Close"]
    if len(close) < 30:
        return None
    rsi = wilder_rsi(close)
    if rsi is None or rsi >= rsi_threshold:
        return None
    decline = float(1 - close.iloc[-1] / close.iloc[-126:].max())
    if decline < min_decline_pct:
        return None
    last = df.iloc[-1]
    bar_range = float(last["High"] - last["Low"])
    upper_half = bar_range > 0 and (last["Close"] - last["Low"]) / bar_range >= 0.5
    if not (float(close.iloc[-1]) > float(close.iloc[-2]) and upper_half):
        return None
    return {
        "symbol": symbol,
        "price": round(float(close.iloc[-1]), 4),
        "rsi": round(rsi, 2),
        "decline_pct": round(decline, 4),
    }

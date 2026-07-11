"""Market overview tool functions.

The one-shot market summary is fast-path only (index and sector ETF
data) so it completes in seconds with no cache warm-up. Top movers,
most-active, and the market heatmap are universe-scale and read the
incremental BreadthStore (slow on first use, incremental after).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import pandas as pd

from quantagent.tools.breadth_store import BreadthStore
from quantagent.tools.market_breadth import (
    compute_market_sentiment,
    compute_percent_above_ma,
    count_distribution_days,
    detect_follow_through_day,
    detect_market_regime,
)
from quantagent.tools.providers.base import AbstractDataProvider
from quantagent.tools.sector_analysis import classify_symbols
from quantagent.tools.technical import detect_support_resistance, wilder_rsi

logger = logging.getLogger(__name__)

_MOVER_PERIOD_DAYS: dict[str, int] = {"1d": 1, "1w": 5, "1m": 21}

_INDEX_ETFS: dict[str, str] = {
    "SPY": "S&P 500",
    "QQQ": "Nasdaq 100",
    "DIA": "Dow Jones",
    "IWM": "Russell 2000",
}


def _index_row(df: pd.DataFrame) -> dict:
    """Price, 1d change, and trend vs 50/200 SMA for one index ETF."""
    close = df["Close"]
    change = (
        round(float(close.iloc[-1] / close.iloc[-2] - 1), 4) if len(close) > 1 else None
    )
    above50 = len(close) >= 50 and float(close.iloc[-1]) > float(close.iloc[-50:].mean())
    above200 = len(close) >= 200 and float(close.iloc[-1]) > float(close.iloc[-200:].mean())
    trend = "up" if above50 and above200 else "down" if not above50 and not above200 else "mixed"
    return {
        "price": round(float(close.iloc[-1]), 4),
        "change_1d": change,
        "trend": trend,
    }


async def get_market_summary(provider: AbstractDataProvider) -> dict:
    """One-shot market overview combining indices, timing, breadth, and regime.

    Fast path only — fetches index ETFs, sector ETFs, and cross-asset
    tickers; no universe-level data required.

    Args:
        provider: Market data provider.

    Returns:
        Dict: {as_of, indices: {symbol: {name, price, change_1d, trend}},
        timing: {distribution_days, follow_through}, breadth,
        regime: {regime, score, confidence, components},
        recommended_exposure, key_levels}.
    """
    index_frames, regime, dist, ftd, breadth, sentiment = await asyncio.gather(
        provider.get_batch_ohlcv(list(_INDEX_ETFS), period="1y"),
        detect_market_regime(provider),
        count_distribution_days(provider),
        detect_follow_through_day(provider),
        compute_percent_above_ma(provider),
        compute_market_sentiment(provider),
    )
    indices = {
        sym: {"name": name, **_index_row(index_frames[sym])}
        for sym, name in _INDEX_ETFS.items()
        if sym in index_frames and not index_frames[sym].empty
    }
    return {
        "as_of": datetime.now(UTC).date().isoformat(),
        "indices": indices,
        "timing": {"distribution_days": dist, "follow_through": ftd},
        "breadth": breadth,
        "sentiment": {"score": sentiment["score"], "label": sentiment["label"]},
        "regime": {k: regime[k] for k in ("regime", "score", "confidence", "components")},
        "recommended_exposure": regime["recommended_exposure"],
        "key_levels": _spy_key_levels(index_frames),
    }


def _spy_key_levels(index_frames: dict[str, pd.DataFrame]) -> dict:
    """Support/resistance for SPY, or empty when data is missing."""
    spy = index_frames.get("SPY")
    if spy is None or spy.empty:
        return {}
    return detect_support_resistance(spy)


async def _universe_matrices(
    provider: AbstractDataProvider, universe: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Close and volume matrices for a universe from the breadth store."""
    store = BreadthStore()
    await store.ensure(provider, universe)
    closes = await store.load_field(universe, "close")
    volumes = await store.load_field(universe, "volume")
    return closes, volumes


async def get_top_movers(
    provider: AbstractDataProvider,
    universe: str = "sp500",
    direction: str = "up",
    count: int = 10,
    period: str = "1d",
) -> pd.DataFrame:
    """Top gainers or losers in a universe (deep path).

    Args:
        provider: Market data provider.
        universe: Universe name (sp500, nasdaq100, sector_etfs).
        direction: "up" for gainers, "down" for losers.
        count: Number of rows returned.
        period: Change window — 1d, 1w, 1m.

    Returns:
        DataFrame with columns: symbol, price, change_pct, volume,
        avg_volume_20d.
    """
    days = _MOVER_PERIOD_DAYS[period]
    closes, volumes = await _universe_matrices(provider, universe)
    if closes.empty or len(closes) <= days:
        return pd.DataFrame()
    change = (closes.iloc[-1] / closes.iloc[-(days + 1)] - 1).dropna()
    ordered = change.sort_values(ascending=direction == "down").head(count)
    return _mover_rows(ordered, closes, volumes, value_name="change_pct")


async def get_most_active(
    provider: AbstractDataProvider,
    universe: str = "sp500",
    count: int = 10,
) -> pd.DataFrame:
    """Most active stocks by volume vs their 20-day average (deep path).

    Args:
        provider: Market data provider.
        universe: Universe name (sp500, nasdaq100, sector_etfs).
        count: Number of rows returned.

    Returns:
        DataFrame with columns: symbol, price, volume_ratio, volume,
        avg_volume_20d.
    """
    closes, volumes = await _universe_matrices(provider, universe)
    if volumes.empty or len(volumes) < 21:
        return pd.DataFrame()
    avg20 = volumes.iloc[-21:-1].mean()
    ratio = (volumes.iloc[-1] / avg20.where(avg20 > 0)).dropna()
    ordered = ratio.sort_values(ascending=False).head(count)
    return _mover_rows(ordered, closes, volumes, value_name="volume_ratio")


def _mover_rows(
    ordered: pd.Series,
    closes: pd.DataFrame,
    volumes: pd.DataFrame,
    value_name: str,
) -> pd.DataFrame:
    """Assemble mover/active rows from the ranked series plus price/volume."""
    avg20 = volumes.iloc[-21:-1].mean() if len(volumes) >= 21 else volumes.mean()
    avg_map = avg20.to_dict()
    rows = [
        {
            "symbol": sym,
            "price": round(float(closes[sym].iloc[-1]), 4),
            value_name: round(float(value), 4),
            "volume": float(volumes[sym].iloc[-1]) if sym in volumes else None,
            "avg_volume_20d": (
                round(float(avg_map[sym]), 2) if sym in avg_map else None
            ),
        }
        for sym, value in ordered.items()
    ]
    return pd.DataFrame(rows)


def _heatmap_value(metric: str, close: pd.Series, volume: pd.Series) -> float | None:
    """Per-symbol heatmap value for the requested metric."""
    if metric == "performance":
        return round(float(close.iloc[-1] / close.iloc[-2] - 1), 4) if len(close) > 1 else None
    if metric == "volatility":
        rets = close.pct_change().iloc[-21:].dropna()
        return round(float(rets.std() * (252**0.5)), 4) if len(rets) >= 5 else None
    if metric == "volume":
        avg = float(volume.iloc[-21:-1].mean()) if len(volume) >= 21 else None
        return round(float(volume.iloc[-1]) / avg, 4) if avg else None
    if metric == "rsi":
        return wilder_rsi(close)
    raise ValueError(f"Unknown heatmap metric: {metric}")


async def generate_market_heatmap(
    provider: AbstractDataProvider,
    universe: str = "sp500",
    metric: str = "performance",
    group_by: str = "sector",
) -> dict:
    """Hierarchical heatmap data grouped by sector/industry (deep path).

    Size is the 20-day average dollar volume (market cap is not stored).

    Args:
        provider: Market data provider.
        universe: Universe name (sp500, nasdaq100).
        metric: performance | volume | volatility | rsi.
        group_by: "sector" (sector -> industry -> symbol) or
            "industry" (industry -> symbol).

    Returns:
        Dict: {metric, group_by, as_of, groups: nested mapping ending in
        {symbol: {value, size}}}.
    """
    if group_by not in ("sector", "industry"):
        raise ValueError(f"Unknown group_by: {group_by}")
    closes, volumes = await _universe_matrices(provider, universe)
    if closes.empty:
        return {"metric": metric, "group_by": group_by, "groups": {}}
    classifications = await classify_symbols(provider, list(closes.columns))
    groups: dict = {}
    for sym in closes.columns:
        cell = _heatmap_cell(metric, closes[sym].dropna(), volumes.get(sym))
        if cell is None:
            continue
        info = classifications.get(sym, {})
        _place_cell(groups, group_by, info, sym, cell)
    return {
        "metric": metric,
        "group_by": group_by,
        "as_of": datetime.now(UTC).date().isoformat(),
        "groups": groups,
    }


def _heatmap_cell(
    metric: str, close: pd.Series, volume: pd.Series | None
) -> dict | None:
    if close.empty or volume is None:
        return None
    value = _heatmap_value(metric, close, volume)
    if value is None:
        return None
    dollar = (close.iloc[-20:] * volume.iloc[-20:]).mean()
    return {"value": value, "size": round(float(dollar), 2) if pd.notna(dollar) else None}


def _place_cell(
    groups: dict, group_by: str, info: dict, symbol: str, cell: dict
) -> None:
    sector = info.get("sector") or "Unknown"
    industry = info.get("industry") or "Unknown"
    if group_by == "sector":
        groups.setdefault(sector, {}).setdefault(industry, {})[symbol] = cell
    else:
        groups.setdefault(industry, {})[symbol] = cell

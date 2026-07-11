"""Market overview tool functions.

One-shot market summary built entirely from the fast path (index and
sector ETF data) so it completes in seconds with no cache warm-up.
Top movers, most-active, and heatmap functions arrive with the
universe-level (deep path) milestone.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import pandas as pd

from quantagent.tools.market_breadth import (
    compute_percent_above_ma,
    count_distribution_days,
    detect_follow_through_day,
    detect_market_regime,
)
from quantagent.tools.providers.base import AbstractDataProvider
from quantagent.tools.technical import detect_support_resistance

logger = logging.getLogger(__name__)

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
    index_frames, regime, dist, ftd, breadth = await asyncio.gather(
        provider.get_batch_ohlcv(list(_INDEX_ETFS), period="1y"),
        detect_market_regime(provider),
        count_distribution_days(provider),
        detect_follow_through_day(provider),
        compute_percent_above_ma(provider),
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

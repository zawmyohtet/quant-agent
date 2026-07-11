"""Earnings event analysis tool functions.

Analyzes how a stock has historically reacted to its earnings reports
(gap, day-1 move, post-event drift) and builds earnings calendars over
a date range for a universe.
"""
from __future__ import annotations

import asyncio
import logging

import pandas as pd

from quantagent.tools.cache import DataCache
from quantagent.tools.providers.base import AbstractDataProvider
from quantagent.utils.progress import report_progress

logger = logging.getLogger(__name__)

_CALENDAR_TTL_SEC = 12 * 3600
_DRIFT_WINDOWS = (5, 20)


async def analyze_earnings_impact(
    provider: AbstractDataProvider,
    symbol: str,
    quarters: int = 8,
) -> dict:
    """Analyze historical price reactions to earnings reports.

    For each past report: the overnight gap into the reaction session,
    the day-1 close-to-close move, and the 5d/20d drift after the
    reaction day (post-earnings-announcement drift context).

    Args:
        provider: Market data provider.
        symbol: Stock ticker symbol.
        quarters: Number of past reports to analyze (default 8).

    Returns:
        Dict: {symbol, events_analyzed, avg_abs_day1_move, positive_rate,
        avg_gap, avg_drift_5d, avg_drift_20d, events: [...]}. Events
        include date, eps_estimate/actual, surprise_pct, gap, day1_move,
        drift_5d, drift_20d.
    """
    symbol = symbol.upper()
    history = await provider.get_earnings_history(symbol, quarters=quarters)
    if not history:
        return {"symbol": symbol, "events_analyzed": 0, "events": []}
    df = await provider.get_ohlcv(symbol, period="2y")
    events = [
        event for raw in history
        if (event := _event_reaction(df, raw)) is not None
    ]
    return {"symbol": symbol, **_aggregate_events(events), "events": events}


def _event_reaction(df: pd.DataFrame, raw: dict) -> dict | None:
    """Compute gap/day-1/drift for one earnings event, or None if out of range."""
    index = pd.DatetimeIndex(df.index)
    event_day = pd.Timestamp(raw["date"]).tz_localize(index.tz)
    positions = df.index.searchsorted(event_day)
    pos = int(positions)
    if pos <= 0 or pos >= len(df):
        return None
    prev_close = float(df["Close"].iloc[pos - 1])
    reaction = df.iloc[pos]
    event = {
        **raw,
        "gap": round(float(reaction["Open"]) / prev_close - 1, 4),
        "day1_move": round(float(reaction["Close"]) / prev_close - 1, 4),
    }
    for window in _DRIFT_WINDOWS:
        drift = None
        if pos + window < len(df):
            drift = round(
                float(df["Close"].iloc[pos + window]) / float(reaction["Close"]) - 1, 4
            )
        event[f"drift_{window}d"] = drift
    return event


def _aggregate_events(events: list[dict]) -> dict:
    """Aggregate per-event reactions into summary statistics."""
    if not events:
        return {"events_analyzed": 0}
    day1 = [e["day1_move"] for e in events]
    return {
        "events_analyzed": len(events),
        "avg_abs_day1_move": round(sum(abs(m) for m in day1) / len(day1), 4),
        "positive_rate": round(sum(1 for m in day1 if m > 0) / len(day1), 4),
        "avg_gap": round(sum(e["gap"] for e in events) / len(events), 4),
        "avg_drift_5d": _mean_or_none([e["drift_5d"] for e in events]),
        "avg_drift_20d": _mean_or_none([e["drift_20d"] for e in events]),
    }


def _mean_or_none(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    if not present:
        return None
    return round(sum(present) / len(present), 4)


async def get_earnings_calendar_range(
    provider: AbstractDataProvider,
    start_date: str,
    end_date: str,
    universe: str | None = None,
    symbols: list[str] | None = None,
) -> pd.DataFrame:
    """Upcoming earnings for a universe within a date range.

    Fetches per-symbol calendars (bounded concurrency, cached 12h) —
    slow on a cold cache for full universes.

    Args:
        provider: Market data provider.
        start_date: Range start (YYYY-MM-DD, inclusive).
        end_date: Range end (YYYY-MM-DD, inclusive).
        universe: Universe to scan (default sp500; ignored when
            ``symbols`` is given).
        symbols: Explicit symbol list.

    Returns:
        DataFrame with columns: symbol, date, eps_estimate, quarter,
        sorted by date.
    """
    if symbols is None:
        from quantagent.tools.screener import _fetch_universe_tickers

        symbols = _fetch_universe_tickers(universe or "sp500")
    events = await _fetch_calendars(provider, [s.upper() for s in symbols])
    rows = [
        {
            "symbol": event["symbol"],
            "date": event["date"][:10],
            "eps_estimate": event.get("eps_estimate"),
            "quarter": event.get("quarter"),
        }
        for event in events
        if start_date <= event["date"][:10] <= end_date
    ]
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


async def _fetch_calendars(
    provider: AbstractDataProvider, symbols: list[str]
) -> list[dict]:
    """Per-symbol upcoming earnings with caching and bounded concurrency."""
    cache = DataCache()
    events: list[dict] = []
    semaphore = asyncio.Semaphore(8)
    fetched = 0

    async def _fetch(sym: str) -> None:
        nonlocal fetched
        key = f"earnings_cal:{sym}"
        cached = await cache.get(key)
        if cached is not None:
            events.extend(cached)
            return
        async with semaphore:
            try:
                calendar = await provider.get_earnings_calendar(sym)
            except Exception as exc:
                logger.debug("Earnings calendar failed for %s: %s", sym, exc)
                return
        fetched += 1
        if fetched % 25 == 0:
            report_progress(f"fetching earnings calendars: {fetched}/{len(symbols)}…")
        await cache.set(key, calendar, ttl=_CALENDAR_TTL_SEC)
        events.extend(calendar)

    async with asyncio.TaskGroup() as tg:
        for sym in symbols:
            tg.create_task(_fetch(sym))
    return events

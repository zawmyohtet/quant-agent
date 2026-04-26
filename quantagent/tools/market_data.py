"""Market data tool functions."""
from __future__ import annotations

import logging

import pandas as pd

from quantagent.tools.providers.base import AbstractDataProvider

logger = logging.getLogger(__name__)


async def get_ohlcv(
    provider: AbstractDataProvider,
    symbol: str,
    period: str = "1y",
    interval: str = "1d",
) -> pd.DataFrame:
    """Fetch OHLCV data for a symbol."""
    return await provider.get_ohlcv(symbol.upper(), period=period, interval=interval)


async def get_quote(provider: AbstractDataProvider, symbol: str) -> dict:
    """Fetch current quote for a symbol."""
    return await provider.get_quote(symbol.upper())


async def get_fundamentals(provider: AbstractDataProvider, symbol: str) -> dict:
    """Fetch fundamental data for a symbol."""
    return await provider.get_fundamentals(symbol.upper())


async def get_earnings_calendar(
    provider: AbstractDataProvider, symbol: str, lookahead_days: int = 90
) -> list[dict]:
    """Fetch upcoming earnings dates."""
    # Not all providers expose earnings calendars directly.
    logger.warning("earnings_calendar not implemented for %s", provider.__class__.__name__)
    return []


async def get_news(
    provider: AbstractDataProvider, symbol: str, days: int = 7
) -> list[dict]:
    """Fetch news headlines for a symbol."""
    return await provider.get_news(symbol.upper(), days=days)


async def search_symbols(provider: AbstractDataProvider, query: str) -> list[dict]:
    """Search for symbols by company name."""
    return await provider.search_symbols(query)


async def get_sector_performance(provider: AbstractDataProvider) -> dict:
    """Fetch sector performance data."""
    logger.warning("sector_performance not implemented for %s", provider.__class__.__name__)
    return {}


async def get_economic_indicators(provider: AbstractDataProvider) -> dict:
    """Fetch economic indicators (VIX, yields, etc.)."""
    logger.warning("economic_indicators not implemented for %s", provider.__class__.__name__)
    return {}

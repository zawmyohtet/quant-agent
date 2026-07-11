"""Abstract data provider interface."""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod

import pandas as pd

logger = logging.getLogger(__name__)

_BATCH_CONCURRENCY = 8


class AbstractDataProvider(ABC):
    """Base class for all market data providers."""

    @abstractmethod
    async def get_ohlcv(
        self, symbol: str, period: str = "1y", interval: str = "1d"
    ) -> pd.DataFrame:
        """Returns DataFrame: columns Open High Low Close Volume, DatetimeIndex UTC."""

    @abstractmethod
    async def get_quote(self, symbol: str) -> dict:
        """Current price, change_pct, volume, market_cap, bid, ask."""

    @abstractmethod
    async def get_fundamentals(self, symbol: str) -> dict:
        """P/E, P/B, EV/EBITDA, ROE, ROA, debt_equity, FCF, dividend_yield, eps."""

    @abstractmethod
    async def search_symbols(self, query: str) -> list[dict]:
        """Search by company name. Returns [{symbol, name, exchange}]."""

    @abstractmethod
    async def get_news(self, symbol: str, days: int = 7) -> list[dict]:
        """Headlines. Returns [{title, source, url, published_at, sentiment}]."""

    @abstractmethod
    async def get_earnings_calendar(
        self, symbol: str, lookahead_days: int = 90
    ) -> list[dict]:
        """Upcoming earnings. Returns [{date, eps_estimate, eps_actual, quarter}]."""

    @abstractmethod
    async def get_sector_performance(self) -> dict:
        """Sector returns. Returns {sector: {1d, 1w, 1m, 3m, ytd, best_stock}}."""

    @abstractmethod
    async def get_economic_indicators(self) -> dict:
        """Macro data. Returns {vix, 10y_yield, 2y_yield, sp500_pe, gdp_growth, cpi, unemployment_rate}."""

    async def get_batch_ohlcv(
        self, symbols: list[str], period: str = "1y", interval: str = "1d"
    ) -> dict[str, pd.DataFrame]:
        """Fetch OHLCV for multiple symbols concurrently.

        Default implementation runs :meth:`get_ohlcv` per symbol with bounded
        concurrency; providers with native batch endpoints should override.
        Symbols that fail are omitted from the result (logged as warnings).
        """
        results: dict[str, pd.DataFrame] = {}
        semaphore = asyncio.Semaphore(_BATCH_CONCURRENCY)

        async def _fetch(sym: str) -> None:
            async with semaphore:
                try:
                    results[sym] = await self.get_ohlcv(sym, period=period, interval=interval)
                except Exception as exc:
                    logger.warning("Batch OHLCV failed for %s: %s", sym, exc)

        async with asyncio.TaskGroup() as tg:
            for sym in symbols:
                tg.create_task(_fetch(sym))
        return results

    async def get_batch_quotes(self, symbols: list[str]) -> dict[str, dict]:
        """Fetch quotes for multiple symbols concurrently.

        Default implementation runs :meth:`get_quote` per symbol with bounded
        concurrency; providers with native batch endpoints should override.
        Symbols that fail are omitted from the result (logged as warnings).
        """
        results: dict[str, dict] = {}
        semaphore = asyncio.Semaphore(_BATCH_CONCURRENCY)

        async def _fetch(sym: str) -> None:
            async with semaphore:
                try:
                    results[sym] = await self.get_quote(sym)
                except Exception as exc:
                    logger.warning("Batch quote failed for %s: %s", sym, exc)

        async with asyncio.TaskGroup() as tg:
            for sym in symbols:
                tg.create_task(_fetch(sym))
        return results

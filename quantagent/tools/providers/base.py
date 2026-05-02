"""Abstract data provider interface."""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


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

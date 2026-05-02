"""Tests for market data tools."""
from __future__ import annotations

import pandas as pd
import pytest

from quantagent.tools.market_data import (
    get_earnings_calendar,
    get_economic_indicators,
    get_fundamentals,
    get_news,
    get_ohlcv,
    get_quote,
    get_sector_performance,
)
from quantagent.tools.providers.base import AbstractDataProvider


class MockProvider(AbstractDataProvider):
    """Mock data provider for testing."""

    async def get_ohlcv(
        self, symbol: str, period: str = "1y", interval: str = "1d"
    ) -> pd.DataFrame:
        dates = pd.date_range("2024-01-01", periods=50, freq="D", tz="UTC")
        return pd.DataFrame(
            {
                "Open": [100.0] * 50,
                "High": [101.0] * 50,
                "Low": [99.0] * 50,
                "Close": [100.0] * 50,
                "Volume": [1_000_000] * 50,
            },
            index=dates,
        )

    async def get_quote(self, symbol: str) -> dict:
        return {"symbol": symbol, "price": 100.0}

    async def get_fundamentals(self, symbol: str) -> dict:
        return {"symbol": symbol, "pe_ratio": 20.0}

    async def search_symbols(self, query: str) -> list[dict]:
        return [{"symbol": "TEST", "name": "Test Corp", "exchange": "NASDAQ"}]

    async def get_news(self, symbol: str, days: int = 7) -> list[dict]:
        return [
            {
                "title": "Test News",
                "source": "Test Source",
                "url": "http://example.com",
                "published_at": "2024-01-01T00:00:00Z",
                "sentiment": "neutral",
            }
        ]

    async def get_earnings_calendar(
        self, symbol: str, lookahead_days: int = 90
    ) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "date": "2024-04-15T00:00:00+00:00",
                "eps_estimate": 1.50,
                "eps_actual": None,
                "quarter": "Q1-2024",
            }
        ]

    async def get_sector_performance(self) -> dict:
        return {
            "Technology": {
                "etf": "XLK",
                "price": 180.0,
                "performance_1d": 0.01,
                "performance_1w": 0.02,
                "performance_1m": 0.05,
                "performance_3m": 0.10,
                "performance_ytd": 0.15,
                "best_stock": None,
            }
        }

    async def get_economic_indicators(self) -> dict:
        return {
            "vix": 18.5,
            "10y_yield": 0.0425,
            "2y_yield": 0.0450,
            "sp500_pe": 22.0,
            "gdp_growth": 0.025,
            "cpi": 310.0,
            "unemployment_rate": 0.038,
        }


@pytest.fixture
def mock_provider():
    return MockProvider()


@pytest.mark.asyncio
async def test_get_ohlcv(mock_provider: MockProvider):
    df = await get_ohlcv(mock_provider, "test")
    assert len(df) == 50
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]


@pytest.mark.asyncio
async def test_get_quote(mock_provider: MockProvider):
    result = await get_quote(mock_provider, "test")
    assert result["symbol"] == "TEST"
    assert result["price"] == 100.0


@pytest.mark.asyncio
async def test_get_fundamentals(mock_provider: MockProvider):
    result = await get_fundamentals(mock_provider, "test")
    assert result["symbol"] == "TEST"
    assert result["pe_ratio"] == 20.0


@pytest.mark.asyncio
async def test_get_news(mock_provider: MockProvider):
    result = await get_news(mock_provider, "test")
    assert len(result) == 1
    assert result[0]["title"] == "Test News"


@pytest.mark.asyncio
async def test_get_earnings_calendar(mock_provider: MockProvider):
    result = await get_earnings_calendar(mock_provider, "test")
    assert len(result) == 1
    assert result[0]["symbol"] == "TEST"
    assert result[0]["eps_estimate"] == 1.50
    assert result[0]["eps_actual"] is None


@pytest.mark.asyncio
async def test_get_sector_performance(mock_provider: MockProvider):
    result = await get_sector_performance(mock_provider)
    assert "Technology" in result
    assert result["Technology"]["etf"] == "XLK"
    assert result["Technology"]["performance_1d"] == 0.01


@pytest.mark.asyncio
async def test_get_economic_indicators(mock_provider: MockProvider):
    result = await get_economic_indicators(mock_provider)
    assert result["vix"] == 18.5
    assert result["10y_yield"] == 0.0425
    assert result["unemployment_rate"] == 0.038

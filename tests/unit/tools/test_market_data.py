"""Tests for market data tools."""
from __future__ import annotations

import pandas as pd
import pytest

from quantagent.tools.market_data import get_fundamentals, get_news, get_ohlcv, get_quote
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

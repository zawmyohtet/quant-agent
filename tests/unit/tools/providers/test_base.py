"""Tests for AbstractDataProvider default batch implementations."""
from __future__ import annotations

import pandas as pd

from quantagent.tools.providers.base import AbstractDataProvider


class MockProvider(AbstractDataProvider):
    """Provider whose per-symbol methods fail for configured symbols."""

    def __init__(self, failing: set[str] | None = None) -> None:
        self.failing = failing or set()

    async def get_ohlcv(
        self, symbol: str, period: str = "1y", interval: str = "1d"
    ) -> pd.DataFrame:
        if symbol in self.failing:
            raise ValueError(f"no data for {symbol}")
        dates = pd.date_range("2024-01-01", periods=10, freq="D", tz="UTC")
        return pd.DataFrame(
            {
                "Open": [100.0] * 10,
                "High": [101.0] * 10,
                "Low": [99.0] * 10,
                "Close": [100.0] * 10,
                "Volume": [1_000_000] * 10,
            },
            index=dates,
        )

    async def get_quote(self, symbol: str) -> dict:
        if symbol in self.failing:
            raise ValueError(f"no quote for {symbol}")
        return {"symbol": symbol, "price": 100.0}

    async def get_fundamentals(self, symbol: str) -> dict:
        return {}

    async def search_symbols(self, query: str) -> list[dict]:
        return []

    async def get_news(self, symbol: str, days: int = 7) -> list[dict]:
        return []

    async def get_earnings_calendar(
        self, symbol: str, lookahead_days: int = 90
    ) -> list[dict]:
        return []

    async def get_sector_performance(self) -> dict:
        return {}

    async def get_economic_indicators(self) -> dict:
        return {}


async def test_get_batch_ohlcv_default() -> None:
    provider = MockProvider()
    result = await provider.get_batch_ohlcv(["AAPL", "MSFT", "GOOG"])
    assert set(result) == {"AAPL", "MSFT", "GOOG"}
    assert all(isinstance(df, pd.DataFrame) for df in result.values())


async def test_get_batch_ohlcv_omits_failures() -> None:
    provider = MockProvider(failing={"MSFT"})
    result = await provider.get_batch_ohlcv(["AAPL", "MSFT"])
    assert set(result) == {"AAPL"}


async def test_get_batch_quotes_default() -> None:
    provider = MockProvider(failing={"BAD"})
    result = await provider.get_batch_quotes(["AAPL", "BAD"])
    assert set(result) == {"AAPL"}
    assert result["AAPL"]["price"] == 100.0


async def test_batch_empty_symbols() -> None:
    provider = MockProvider()
    assert await provider.get_batch_ohlcv([]) == {}
    assert await provider.get_batch_quotes([]) == {}

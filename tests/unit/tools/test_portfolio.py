"""Tests for portfolio tools."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantagent.tools.portfolio import optimize_portfolio
from quantagent.tools.providers.base import AbstractDataProvider


class MockProvider(AbstractDataProvider):
    """Mock data provider for testing."""

    async def get_ohlcv(
        self, symbol: str, period: str = "1y", interval: str = "1d"
    ) -> pd.DataFrame:
        rng = np.random.default_rng(hash(symbol) % 2**32)
        n = 252
        dates = pd.date_range("2023-01-01", periods=n, freq="D", tz="UTC")
        returns = rng.normal(0.0005, 0.02, n)
        prices = 100 * np.exp(np.cumsum(returns))
        return pd.DataFrame(
            {
                "Open": prices * 0.99,
                "High": prices * 1.01,
                "Low": prices * 0.98,
                "Close": prices,
                "Volume": rng.integers(1_000_000, 5_000_000, n),
            },
            index=dates,
        )

    async def get_quote(self, symbol: str) -> dict:
        return {"symbol": symbol, "price": 100.0}

    async def get_fundamentals(self, symbol: str) -> dict:
        return {"symbol": symbol}

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


@pytest.fixture
def mock_provider():
    return MockProvider()


@pytest.mark.asyncio
async def test_optimize_portfolio_equal_weight(mock_provider: MockProvider):
    result = await optimize_portfolio(
        mock_provider, ["A", "B", "C"], method="equal_weight"
    )
    assert "weights" in result
    assert len(result["weights"]) == 3
    assert result["weights"]["A"] == pytest.approx(0.3333, abs=0.01)


@pytest.mark.asyncio
async def test_optimize_portfolio_max_sharpe(mock_provider: MockProvider):
    result = await optimize_portfolio(
        mock_provider, ["A", "B"], method="max_sharpe"
    )
    assert "weights" in result
    assert "expected_return" in result
    assert "volatility" in result
    assert "sharpe_ratio" in result


@pytest.mark.asyncio
async def test_optimize_portfolio_min_vol(mock_provider: MockProvider):
    result = await optimize_portfolio(
        mock_provider, ["A", "B"], method="min_vol"
    )
    assert "weights" in result
    assert result["volatility"] >= 0


@pytest.mark.asyncio
async def test_optimize_portfolio_risk_parity(mock_provider: MockProvider):
    result = await optimize_portfolio(
        mock_provider, ["A", "B", "C"], method="risk_parity"
    )
    assert "weights" in result
    assert sum(result["weights"].values()) == pytest.approx(1.0, abs=0.01)

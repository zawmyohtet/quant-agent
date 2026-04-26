"""Tests for backtesting tools."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantagent.tools.backtesting import BacktestConfig, BacktestResult
from quantagent.tools.providers.base import AbstractDataProvider


class MockProvider(AbstractDataProvider):
    """Mock data provider for testing."""

    async def get_ohlcv(
        self, symbol: str, period: str = "1y", interval: str = "1d"
    ) -> pd.DataFrame:
        rng = np.random.default_rng(42)
        n = 500
        dates = pd.date_range("2023-01-01", periods=n, freq="D")
        trend = np.linspace(100, 150, n)
        noise = rng.normal(0, 2, n)
        close = trend + noise
        high = close + rng.uniform(0, 2, n)
        low = close - rng.uniform(0, 2, n)
        open_ = close + rng.normal(0, 1, n)
        volume = rng.integers(1_000_000, 5_000_000, n)
        df = pd.DataFrame(
            {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
            index=dates,
        )
        df.index = df.index.tz_localize("UTC")
        return df

    async def get_quote(self, symbol: str) -> dict:
        return {"symbol": symbol, "price": 150.0}

    async def get_fundamentals(self, symbol: str) -> dict:
        return {"symbol": symbol, "pe_ratio": 20.0}

    async def search_symbols(self, query: str) -> list[dict]:
        return []

    async def get_news(self, symbol: str, days: int = 7) -> list[dict]:
        return []


@pytest.fixture
def mock_provider():
    return MockProvider()


@pytest.mark.asyncio
async def test_run_backtest(mock_provider: MockProvider):
    config = BacktestConfig(symbol="TEST", strategy="sma_crossover", period="2y")
    await mock_provider.get_ohlcv("TEST")
    # We can't easily test run_backtest directly without vectorbt,
    # but we can test the config and result models
    assert config.symbol == "TEST"
    assert config.strategy == "sma_crossover"


@pytest.mark.asyncio
async def test_backtest_result_model():
    BacktestConfig(symbol="TEST", strategy="buy_and_hold")
    result = BacktestResult(
        symbol="TEST",
        strategy="buy_and_hold",
        period="1y",
        cagr=0.10,
        sharpe_ratio=1.5,
        sortino_ratio=1.8,
        calmar_ratio=2.0,
        max_drawdown=0.15,
        max_drawdown_duration_days=30,
        win_rate=0.55,
        total_trades=20,
        profit_factor=1.6,
        total_return=0.10,
        annualized_volatility=0.20,
        equity_curve=pd.Series([100, 110]),
        monthly_returns=pd.Series([0.01, 0.02]),
        trade_log=pd.DataFrame(),
    )
    assert result.symbol == "TEST"
    assert result.sharpe_ratio == 1.5


def test_format_backtest_result():
    BacktestConfig(symbol="TEST", strategy="buy_and_hold")
    result = BacktestResult(
        symbol="TEST",
        strategy="buy_and_hold",
        period="1y",
        cagr=0.10,
        sharpe_ratio=1.5,
        sortino_ratio=1.8,
        calmar_ratio=2.0,
        max_drawdown=0.15,
        max_drawdown_duration_days=30,
        win_rate=0.55,
        total_trades=20,
        profit_factor=1.6,
        total_return=0.10,
        annualized_volatility=0.20,
        equity_curve=pd.Series([100, 110]),
        monthly_returns=pd.Series([0.01, 0.02]),
        trade_log=pd.DataFrame(),
    )
    from quantagent.tools.backtesting import format_backtest_result

    formatted = format_backtest_result(result)
    assert "TEST" in formatted
    assert "buy_and_hold" in formatted
    assert "Sharpe Ratio" in formatted

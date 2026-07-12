"""Tests for backtesting tools."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantagent.tools.backtesting import (
    BacktestConfig,
    BacktestResult,
    _evaluate_combo,
    format_backtest_result,
    optimize_parameters,
    run_backtest,
    run_walkforward,
)
from quantagent.tools.providers.base import AbstractDataProvider


def _synthetic_ohlcv(n: int = 500) -> pd.DataFrame:
    dates = pd.date_range("2023-01-01", periods=n, freq="D", tz="UTC")
    rng = np.random.default_rng(42)
    trend = np.linspace(100, 110, n)
    noise = rng.normal(0, 1.5, n)
    close = trend + noise
    high = close + rng.uniform(0, 2, n)
    low = close - rng.uniform(0, 2, n)
    open_ = close + rng.normal(0, 1, n)
    volume = rng.integers(1_000_000, 5_000_000, n)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=dates,
    )


class MockProvider(AbstractDataProvider):
    def __init__(self, df: pd.DataFrame) -> None:
        self.df = df

    async def get_ohlcv(
        self, symbol: str, period: str = "1y", interval: str = "1d"
    ) -> pd.DataFrame:
        return self.df

    async def get_quote(self, symbol: str) -> dict:
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


def test_backtest_result_model() -> None:
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


def test_format_backtest_result() -> None:
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
    formatted = format_backtest_result(result)
    assert "TEST" in formatted
    assert "buy_and_hold" in formatted
    assert "Sharpe Ratio" in formatted


async def test_run_backtest_buy_and_hold() -> None:
    df = _synthetic_ohlcv(500)
    provider = MockProvider(df)
    config = BacktestConfig(symbol="TEST", strategy="buy_and_hold", period="2y")
    result = await run_backtest(provider, config)
    assert result.symbol == "TEST"
    assert result.strategy == "buy_and_hold"
    assert result.cagr is not None
    assert result.sharpe_ratio is not None
    assert result.total_return is not None
    assert len(result.equity_curve) > 0


async def test_run_backtest_sma_crossover() -> None:
    df = _synthetic_ohlcv(500)
    provider = MockProvider(df)
    config = BacktestConfig(symbol="TEST", strategy="sma_crossover", period="2y")
    result = await run_backtest(provider, config)
    assert result.sharpe_ratio is not None


async def test_run_backtest_with_stop_loss() -> None:
    df = _synthetic_ohlcv(500)
    provider = MockProvider(df)
    config = BacktestConfig(
        symbol="TEST", strategy="buy_and_hold", period="2y", stop_loss_pct=0.05,
    )
    result = await run_backtest(provider, config)
    assert result.total_trades >= 0


async def test_run_backtest_insufficient_data() -> None:
    df = _synthetic_ohlcv(10)
    provider = MockProvider(df)
    config = BacktestConfig(symbol="TEST", strategy="buy_and_hold", period="1mo")
    with pytest.raises(ValueError, match="Insufficient data"):
        await run_backtest(provider, config)


async def test_run_walkforward() -> None:
    df = _synthetic_ohlcv(600)
    provider = MockProvider(df)
    config = BacktestConfig(symbol="TEST", strategy="buy_and_hold", period="2y")
    results = await run_walkforward(provider, config, n_splits=3, train_ratio=0.7)
    assert len(results) == 3
    assert all(r.symbol == "TEST" for r in results)


async def test_run_walkforward_insufficient_data() -> None:
    df = _synthetic_ohlcv(50)
    provider = MockProvider(df)
    config = BacktestConfig(symbol="TEST", strategy="buy_and_hold", period="1mo")
    with pytest.raises(ValueError, match="Insufficient data for walk-forward"):
        await run_walkforward(provider, config, n_splits=5)


async def test_optimize_parameters() -> None:
    df = _synthetic_ohlcv(500)
    provider = MockProvider(df)
    config = BacktestConfig(symbol="TEST", strategy="buy_and_hold", period="2y")
    param_grid = {"fast": [10, 20], "slow": [50, 100]}
    result = await optimize_parameters(provider, config, param_grid, metric="sharpe_ratio")
    assert "best_params" in result
    assert "best_sharpe_ratio" in result
    assert "all_results" in result
    assert len(result["all_results"]) > 0


async def test_optimize_parameters_insufficient_data() -> None:
    df = _synthetic_ohlcv(10)
    provider = MockProvider(df)
    config = BacktestConfig(symbol="TEST", strategy="buy_and_hold", period="1mo")
    with pytest.raises(ValueError, match="Insufficient data for optimization"):
        await optimize_parameters(provider, config, {"fast": [10]})


def test_evaluate_combo_success() -> None:
    df = _synthetic_ohlcv(500)
    config = BacktestConfig(symbol="TEST", strategy="buy_and_hold", period="2y")
    result = _evaluate_combo(df, config, "sharpe_ratio", {"param": 1})
    assert result is not None
    entry, value = result
    assert "sharpe_ratio" in entry
    assert "params" in entry
    assert entry["params"] == {"param": 1}
    assert isinstance(value, float)


def test_evaluate_combo_failure() -> None:
    df = pd.DataFrame({"Close": [100.0], "Open": [99.0], "High": [101.0], "Low": [98.0], "Volume": [1_000_000]})
    config = BacktestConfig(symbol="TEST", strategy="buy_and_hold", period="1mo")
    result = _evaluate_combo(df, config, "nonexistent_metric", {"param": 1})
    assert result is None

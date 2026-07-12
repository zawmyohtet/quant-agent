"""Tests for portfolio optimization tools."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantagent.tools.portfolio import (
    _compute_beta,
    _compute_tracking_info,
    _compute_var_cvar,
    _equal_weight_weights,
    _fetch_prices,
    _max_sharpe,
    _min_volatility,
    _risk_parity,
    compute_portfolio_metrics,
    monte_carlo_simulation,
    optimize_portfolio,
)
from quantagent.tools.providers.base import AbstractDataProvider


class MockProvider(AbstractDataProvider):
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.frames = frames

    async def get_batch_ohlcv(
        self, symbols: list[str], period: str = "1y"
    ) -> dict[str, pd.DataFrame]:
        return {s: self.frames.get(s) for s in symbols if s in self.frames}

    async def get_ohlcv(
        self, symbol: str, period: str = "1y", interval: str = "1d"
    ) -> pd.DataFrame:
        return self.frames.get(symbol, pd.DataFrame())

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


@pytest.fixture
def stock_frames() -> dict[str, pd.DataFrame]:
    dates = pd.date_range("2024-01-01", periods=252, freq="D", tz="UTC")
    rng = np.random.default_rng(42)
    frames = {}
    for sym in ["AAPL", "MSFT", "GOOG", "SPY"]:
        price = 100.0 + np.cumsum(rng.normal(0, 0.5, 252))
        frames[sym] = pd.DataFrame(
            {"Close": price, "Open": price * 0.99, "High": price * 1.01, "Low": price * 0.99, "Volume": 1_000_000},
            index=dates,
        )
    return frames


async def test_optimize_portfolio_equal_weight(stock_frames: dict[str, pd.DataFrame]) -> None:
    provider = MockProvider(stock_frames)
    result = await optimize_portfolio(provider, ["AAPL", "MSFT", "GOOG"], method="equal_weight")
    assert "weights" in result
    assert abs(sum(result["weights"].values()) - 1.0) < 0.01
    assert result["method"] == "equal_weight"


async def test_optimize_portfolio_max_sharpe(stock_frames: dict[str, pd.DataFrame]) -> None:
    provider = MockProvider(stock_frames)
    result = await optimize_portfolio(provider, ["AAPL", "MSFT", "GOOG"], method="max_sharpe")
    assert "sharpe_ratio" in result


async def test_optimize_portfolio_min_vol(stock_frames: dict[str, pd.DataFrame]) -> None:
    provider = MockProvider(stock_frames)
    result = await optimize_portfolio(provider, ["AAPL", "MSFT", "GOOG"], method="min_vol")
    assert "volatility" in result


async def test_optimize_portfolio_risk_parity(stock_frames: dict[str, pd.DataFrame]) -> None:
    provider = MockProvider(stock_frames)
    result = await optimize_portfolio(provider, ["AAPL", "MSFT", "GOOG"], method="risk_parity")
    assert "weights" in result


async def test_optimize_portfolio_unknown_method(stock_frames: dict[str, pd.DataFrame]) -> None:
    provider = MockProvider(stock_frames)
    with pytest.raises(ValueError, match="Unknown optimization method"):
        await optimize_portfolio(provider, ["AAPL", "MSFT"], method="unknown_method")


async def test_optimize_portfolio_empty_frames(stock_frames: dict[str, pd.DataFrame]) -> None:
    provider = MockProvider({})
    with pytest.raises(ValueError, match="No price data fetched"):
        await optimize_portfolio(provider, ["MISSING"], method="equal_weight")


async def test_optimize_portfolio_single_symbol() -> None:
    frames = {"AAPL": pd.DataFrame()}
    provider = MockProvider(frames)
    with pytest.raises(ValueError, match="No price data"):
        await optimize_portfolio(provider, ["AAPL"], method="equal_weight")


async def test_compute_portfolio_metrics(stock_frames: dict[str, pd.DataFrame]) -> None:
    provider = MockProvider(stock_frames)
    weights = {"AAPL": 0.5, "MSFT": 0.5}
    result = await compute_portfolio_metrics(provider, weights, period="1y", benchmark="SPY")
    assert "beta" in result
    assert "var_95" in result
    assert "var_99" in result
    assert "cvar_95" in result
    assert "tracking_error" in result
    assert "information_ratio" in result


async def test_compute_portfolio_metrics_insufficient_data() -> None:
    provider = MockProvider({})
    with pytest.raises(ValueError, match="No price data"):
        await compute_portfolio_metrics(provider, {"AAPL": 1.0})


async def test_monte_carlo_simulation(stock_frames: dict[str, pd.DataFrame]) -> None:
    provider = MockProvider(stock_frames)
    weights = {"AAPL": 0.5, "MSFT": 0.5}
    result = await monte_carlo_simulation(provider, weights, horizon_days=10, n_simulations=100)
    assert "p5" in result
    assert "p50" in result
    assert "p95" in result
    assert "prob_loss" in result


async def test_monte_carlo_insufficient_data() -> None:
    provider = MockProvider({})
    with pytest.raises(ValueError, match="No price data"):
        await monte_carlo_simulation(provider, {"AAPL": 1.0})


async def test_fetch_prices(stock_frames: dict[str, pd.DataFrame]) -> None:
    provider = MockProvider(stock_frames)
    prices = await _fetch_prices(provider, ["AAPL", "MSFT"], "1y")
    assert "AAPL" in prices.columns
    assert "MSFT" in prices.columns


async def test_fetch_prices_no_data() -> None:
    provider = MockProvider({})
    with pytest.raises(ValueError, match="No price data"):
        await _fetch_prices(provider, ["MISSING"], "1y")


def test_equal_weight_weights() -> None:
    returns = pd.Series([0.1, 0.2, 0.3])
    weights = _equal_weight_weights(returns, pd.DataFrame(), None)
    assert np.allclose(weights, [1/3, 1/3, 1/3])


def test_max_sharpe() -> None:
    mean_returns = pd.Series([0.10, 0.12, 0.08])
    cov = pd.DataFrame(np.eye(3) * 0.04)
    weights = _max_sharpe(mean_returns, cov, None)
    assert abs(weights.sum() - 1.0) < 0.01
    assert all(w >= 0 for w in weights)


def test_max_sharpe_with_bounds() -> None:
    mean_returns = pd.Series([0.10, 0.12])
    cov = pd.DataFrame(np.eye(2) * 0.04)
    weights = _max_sharpe(mean_returns, cov, {"bounds": [(0.0, 0.6)] * 2})
    assert abs(weights.sum() - 1.0) < 0.01


def test_min_volatility() -> None:
    mean_returns = pd.Series([0.10, 0.12])
    cov = pd.DataFrame([[0.04, 0.01], [0.01, 0.05]])
    weights = _min_volatility(mean_returns, cov, None)
    assert abs(weights.sum() - 1.0) < 0.01


def test_risk_parity() -> None:
    cov = pd.DataFrame([[0.04, 0.01], [0.01, 0.09]])
    weights = _risk_parity(cov)
    assert abs(weights.sum() - 1.0) < 0.01


def test_compute_beta() -> None:
    port_returns = pd.Series([0.01, 0.02, -0.01, 0.03])
    bench_returns = pd.Series([0.005, 0.015, -0.005, 0.02])
    beta = _compute_beta(port_returns, bench_returns)
    assert abs(beta - 1.0) < 1.0


def test_compute_beta_zero_variance() -> None:
    port_returns = pd.Series([0.01, 0.02, 0.01])
    bench_returns = pd.Series([0.01, 0.01, 0.01])
    beta = _compute_beta(port_returns, bench_returns)
    assert beta == 0.0


def test_compute_var_cvar() -> None:
    returns = pd.Series([-0.05, -0.03, 0.01, 0.02, -0.02, 0.03])
    var_95, var_99, cvar_95 = _compute_var_cvar(returns)
    assert var_95 < 0
    assert var_99 < 0


def test_compute_var_cvar_no_tail() -> None:
    returns = pd.Series([0.01] * 20)
    var_95, var_99, cvar_95 = _compute_var_cvar(returns)
    assert abs(cvar_95 - 0.01) < 1e-10  # all values identical, avg of values <= var_95


def test_compute_tracking_info() -> None:
    port = pd.Series([0.02, 0.01, -0.01, 0.03])
    bench = pd.Series([0.01, 0.0, 0.0, 0.01])
    tracking_error, info_ratio = _compute_tracking_info(port, bench)
    assert tracking_error > 0

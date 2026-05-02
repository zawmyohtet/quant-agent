"""Portfolio optimization tool functions."""
from __future__ import annotations

import logging
from collections.abc import Callable

import numpy as np
import pandas as pd
from scipy.optimize import minimize  # type: ignore[import-untyped]

from quantagent.tools.providers.base import AbstractDataProvider

logger = logging.getLogger(__name__)


def _equal_weight_weights(
    _mean_returns: pd.Series, _cov_matrix: pd.DataFrame, _constraints: dict | None
) -> np.ndarray:
    n = len(_mean_returns)
    return np.ones(n) / n


async def optimize_portfolio(
    provider: AbstractDataProvider,
    symbols: list[str],
    method: str = "max_sharpe",
    period: str = "2y",
    constraints: dict | None = None,
) -> dict:
    """Optimize portfolio weights.

    Methods: max_sharpe, min_vol, risk_parity, equal_weight.

    Returns:
        Dict with weights, expected_return, volatility, sharpe_ratio.
    """
    constraints = constraints or {}
    prices = await _fetch_prices(provider, symbols, period)
    returns = prices.pct_change().dropna()

    if returns.empty or len(returns.columns) < 2:
        raise ValueError("Insufficient price data for portfolio optimization")

    mean_returns = returns.mean() * 252
    cov_matrix = returns.cov() * 252

    optimizer = _METHOD_DISPATCH.get(method)
    if optimizer is None:
        raise ValueError(f"Unknown optimization method: {method}")

    weights = optimizer(mean_returns, cov_matrix, constraints)
    weights = np.maximum(weights, 0)  # No short selling
    weights = weights / weights.sum()

    port_return = float(np.dot(weights, mean_returns))
    port_vol = float(np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights))))
    sharpe = port_return / port_vol if port_vol > 0 else 0.0

    return {
        "weights": {sym: round(float(w), 4) for sym, w in zip(symbols, weights, strict=False)},
        "expected_return": round(port_return, 4),
        "volatility": round(port_vol, 4),
        "sharpe_ratio": round(sharpe, 4),
        "method": method,
    }


def _compute_beta(port_returns: pd.Series, bench_returns: pd.Series) -> float:
    cov = np.cov(port_returns.dropna(), bench_returns.dropna())
    return cov[0, 1] / cov[1, 1] if cov[1, 1] != 0 else 0.0


def _compute_var_cvar(port_returns: pd.Series) -> tuple[float, float, float]:
    var_95 = float(np.percentile(port_returns, 5))
    var_99 = float(np.percentile(port_returns, 1))
    cvar_95 = float(port_returns[port_returns <= var_95].mean()) if (port_returns <= var_95).any() else 0.0
    return var_95, var_99, cvar_95


def _compute_tracking_info(port_returns: pd.Series, bench_returns: pd.Series) -> tuple[float, float]:
    active_returns = port_returns - bench_returns
    tracking_error = float(active_returns.std() * np.sqrt(252))
    info_ratio = float(active_returns.mean() * 252 / tracking_error) if tracking_error > 0 else 0.0
    return tracking_error, info_ratio


async def compute_portfolio_metrics(
    provider: AbstractDataProvider,
    weights: dict[str, float],
    period: str = "1y",
    benchmark: str = "SPY",
) -> dict:
    """Compute portfolio risk metrics.

    Returns:
        Dict with beta, var_95, var_99, cvar_95, tracking_error,
        information_ratio.
    """
    symbols = list(weights.keys()) + [benchmark]
    prices = await _fetch_prices(provider, symbols, period)
    returns = prices.pct_change().dropna()

    if returns.empty:
        raise ValueError("Insufficient price data for portfolio metrics")

    port_returns = pd.Series(0.0, index=returns.index)
    for sym, w in weights.items():
        if sym in returns.columns:
            port_returns += returns[sym] * w

    bench_returns = returns[benchmark] if benchmark in returns.columns else pd.Series(0.0, index=returns.index)

    var_95, var_99, cvar_95 = _compute_var_cvar(port_returns)
    tracking_error, information_ratio = _compute_tracking_info(port_returns, bench_returns)

    return {
        "beta": round(_compute_beta(port_returns, bench_returns), 4),
        "var_95": round(var_95, 4),
        "var_99": round(var_99, 4),
        "cvar_95": round(cvar_95, 4),
        "tracking_error": round(tracking_error, 4),
        "information_ratio": round(information_ratio, 4),
    }


async def monte_carlo_simulation(
    provider: AbstractDataProvider,
    weights: dict[str, float],
    horizon_days: int = 252,
    n_simulations: int = 1000,
) -> dict:
    """Run Monte Carlo simulation for portfolio.

    Returns:
        Dict with p5, p25, p50, p75, p95, prob_loss, expected_value.
    """
    symbols = list(weights.keys())
    prices = await _fetch_prices(provider, symbols, "2y")
    returns = prices.pct_change().dropna()

    if returns.empty:
        raise ValueError("Insufficient price data for Monte Carlo simulation")

    mean_returns = returns.mean()
    cov_matrix = returns.cov()
    w = np.array([weights.get(s, 0.0) for s in symbols])

    rng = np.random.default_rng(42)
    simulated = rng.multivariate_normal(mean_returns, cov_matrix, size=(n_simulations, horizon_days))
    port_simulated = np.dot(simulated, w)
    cumulative = np.cumprod(1 + port_simulated, axis=1)
    final_values = cumulative[:, -1]

    return {
        "p5": round(float(np.percentile(final_values, 5)), 4),
        "p25": round(float(np.percentile(final_values, 25)), 4),
        "p50": round(float(np.percentile(final_values, 50)), 4),
        "p75": round(float(np.percentile(final_values, 75)), 4),
        "p95": round(float(np.percentile(final_values, 95)), 4),
        "prob_loss": round(float(np.mean(final_values < 1.0)), 4),
        "expected_value": round(float(np.mean(final_values)), 4),
    }


async def _fetch_single_price(
    provider: AbstractDataProvider, symbol: str, period: str
) -> tuple[str, pd.Series | None]:
    """Fetch closing price for a single symbol. Returns (symbol, Close | None)."""
    try:
        df = await provider.get_ohlcv(symbol, period=period)
        return symbol, df["Close"] if not df.empty else None
    except Exception as exc:
        logger.warning("Failed to fetch prices for %s: %s", symbol, exc)
        return symbol, None


async def _fetch_prices(
    provider: AbstractDataProvider, symbols: list[str], period: str
) -> pd.DataFrame:
    """Fetch closing prices for multiple symbols."""
    prices: dict[str, pd.Series] = {}
    for sym in symbols:
        _, close = await _fetch_single_price(provider, sym, period)
        if close is not None:
            prices[sym] = close
    if not prices:
        raise ValueError("No price data fetched for any symbol")
    return pd.DataFrame(prices).dropna()


def _max_sharpe(
    mean_returns: pd.Series, cov_matrix: pd.DataFrame, constraints: dict | None
) -> np.ndarray:
    """Optimize for maximum Sharpe ratio (assume rf=0 for simplicity)."""
    n = len(mean_returns)
    bounds = (constraints or {}).get("bounds", [(0.0, 1.0)] * n)

    def neg_sharpe(w: np.ndarray) -> float:
        p_ret = np.dot(w, mean_returns)
        p_vol = np.sqrt(np.dot(w.T, np.dot(cov_matrix, w)))
        return -(p_ret / p_vol) if p_vol > 0 else 0.0

    result = minimize(
        neg_sharpe,
        np.ones(n) / n,
        method="SLSQP",
        bounds=bounds,
        constraints={"type": "eq", "fun": lambda w: np.sum(w) - 1.0},
    )
    return result.x if result.success else np.ones(n) / n


def _min_volatility(
    mean_returns: pd.Series, cov_matrix: pd.DataFrame, constraints: dict | None
) -> np.ndarray:
    """Optimize for minimum volatility."""
    n = len(mean_returns)
    bounds = (constraints or {}).get("bounds", [(0.0, 1.0)] * n)

    def volatility(w: np.ndarray) -> float:
        return float(np.sqrt(np.dot(w.T, np.dot(cov_matrix, w))))

    result = minimize(
        volatility,
        np.ones(n) / n,
        method="SLSQP",
        bounds=bounds,
        constraints={"type": "eq", "fun": lambda w: np.sum(w) - 1.0},
    )
    return result.x if result.success else np.ones(n) / n


def _risk_parity(cov_matrix: pd.DataFrame) -> np.ndarray:
    """Compute risk parity weights."""
    inv_diag = 1.0 / np.diag(cov_matrix.values)
    weights = inv_diag / inv_diag.sum()
    return weights  # type: ignore[no-any-return]


_METHOD_DISPATCH: dict[
    str, Callable[[pd.Series, pd.DataFrame, dict | None], np.ndarray]
] = {
    "equal_weight": _equal_weight_weights,
    "min_vol": _min_volatility,
    "max_sharpe": _max_sharpe,
    "risk_parity": lambda _mr, cov, _c: _risk_parity(cov),
}

"""Backtesting tool functions."""
from __future__ import annotations

import logging
from itertools import product

import numpy as np
import pandas as pd
import vectorbt as vbt  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict

from quantagent.tools.providers.base import AbstractDataProvider
from quantagent.tools.technical import generate_signals

logger = logging.getLogger(__name__)


class BacktestConfig(BaseModel):
    """Configuration for a backtest run."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    symbol: str
    strategy: str
    period: str = "5y"
    initial_capital: float = 100_000.0
    commission: float = 0.001
    position_size: float = 1.0
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    custom_signals: pd.Series | None = None


class BacktestResult(BaseModel):
    """Results from a backtest run."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    symbol: str
    strategy: str
    period: str
    cagr: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown: float
    max_drawdown_duration_days: int
    win_rate: float
    total_trades: int
    profit_factor: float
    total_return: float
    annualized_volatility: float
    equity_curve: pd.Series
    monthly_returns: pd.Series
    trade_log: pd.DataFrame


async def run_backtest(
    provider: AbstractDataProvider, config: BacktestConfig
) -> BacktestResult:
    """Run a single backtest for a symbol and strategy."""
    df = await provider.get_ohlcv(config.symbol, period=config.period)
    if len(df) < 50:
        raise ValueError(f"Insufficient data for {config.symbol}: {len(df)} bars")

    # Generate signals
    signals_df = generate_signals(df, config.strategy)
    entries = signals_df["Signal"] == 1
    exits = signals_df["Signal"] == -1

    # Apply stop loss / take profit if specified
    sl_stop = config.stop_loss_pct if config.stop_loss_pct else np.nan
    tp_stop = config.take_profit_pct if config.take_profit_pct else np.nan

    # Run vectorbt backtest
    pf = vbt.Portfolio.from_signals(
        signals_df["Close"],
        entries,
        exits,
        freq="1d",
        init_cash=config.initial_capital,
        fees=config.commission,
        sl_stop=sl_stop,
        tp_stop=tp_stop,
    )

    return _portfolio_to_result(pf, config)


def _portfolio_to_result(pf: vbt.Portfolio, config: BacktestConfig) -> BacktestResult:
    """Convert a vectorbt Portfolio to BacktestResult."""
    total_return = float(pf.total_return())
    n_years = len(pf.returns()) / 252
    cagr = (1 + total_return) ** (1 / n_years) - 1 if n_years > 0 else 0.0

    # Max drawdown duration
    mdd = pf.drawdowns.max_duration()
    mdd_days = mdd.days if hasattr(mdd, "days") else int(mdd)

    # Monthly returns
    monthly = pf.returns().resample("ME").apply(lambda x: (1 + x).prod() - 1)

    # Trade log
    trade_log = pf.trades.records_readable if pf.trades.count() > 0 else pd.DataFrame()

    return BacktestResult(
        symbol=config.symbol,
        strategy=config.strategy,
        period=config.period,
        cagr=round(cagr, 4),
        sharpe_ratio=round(float(pf.sharpe_ratio()), 4),
        sortino_ratio=round(float(pf.sortino_ratio()), 4),
        calmar_ratio=round(float(pf.calmar_ratio()), 4),
        max_drawdown=round(abs(float(pf.max_drawdown())), 4),
        max_drawdown_duration_days=mdd_days,
        win_rate=round(float(pf.trades.win_rate()), 4),
        total_trades=int(pf.trades.count()),
        profit_factor=round(float(pf.trades.profit_factor()), 4),
        total_return=round(total_return, 4),
        annualized_volatility=round(float(pf.annualized_volatility()), 4),
        equity_curve=pf.value(),
        monthly_returns=monthly,
        trade_log=trade_log,
    )


async def run_walkforward(
    provider: AbstractDataProvider,
    config: BacktestConfig,
    n_splits: int = 5,
    train_ratio: float = 0.7,
) -> list[BacktestResult]:
    """Run walk-forward analysis with train/test splits."""
    df = await provider.get_ohlcv(config.symbol, period=config.period)
    if len(df) < n_splits * 100:
        raise ValueError(f"Insufficient data for walk-forward: {len(df)} bars")

    split_size = len(df) // n_splits
    results = []

    for i in range(n_splits):
        start_idx = i * split_size
        end_idx = start_idx + split_size
        split_df = df.iloc[start_idx:end_idx]

        train_end = int(len(split_df) * train_ratio)
        split_df.iloc[:train_end]
        test_df = split_df.iloc[train_end:]

        # In a real implementation, parameters would be optimized on train_df
        # and evaluated on test_df. For simplicity, we run the same strategy.
        test_signals = generate_signals(test_df, config.strategy)
        entries = test_signals["Signal"] == 1
        exits = test_signals["Signal"] == -1

        pf = vbt.Portfolio.from_signals(
            test_signals["Close"],
            entries,
            exits,
            freq="1d",
            init_cash=config.initial_capital,
            fees=config.commission,
        )

        results.append(_portfolio_to_result(pf, config))

    return results


def _evaluate_combo(
    df: pd.DataFrame, config: BacktestConfig, metric: str, params: dict
) -> tuple[dict, float] | None:
    """Run a backtest for a single parameter combo and return (result, metric_value) or None."""
    try:
        signals_df = generate_signals(df, config.strategy)
        entries = signals_df["Signal"] == 1
        exits = signals_df["Signal"] == -1

        pf = vbt.Portfolio.from_signals(
            signals_df["Close"],
            entries,
            exits,
            freq="1d",
            init_cash=config.initial_capital,
            fees=config.commission,
        )

        metric_value = float(getattr(pf, metric)())
        return {"params": params, metric: round(metric_value, 4)}, metric_value
    except Exception as exc:
        logger.warning("Optimization failed for params %s: %s", params, exc)
        return None


async def optimize_parameters(
    provider: AbstractDataProvider,
    config: BacktestConfig,
    param_grid: dict,
    metric: str = "sharpe_ratio",
) -> dict:
    """Optimize strategy parameters via grid search.

    Args:
        param_grid: Dict of parameter names to lists of values.
            Example: {"fast": [10, 20, 50], "slow": [50, 100, 200]}
        metric: Metric to maximize (sharpe_ratio, total_return, etc.)

    Returns:
        Dict with best_params, best_metric_value, and all_results.
    """
    df = await provider.get_ohlcv(config.symbol, period=config.period)
    if len(df) < 50:
        raise ValueError(f"Insufficient data for optimization: {len(df)} bars")

    keys = list(param_grid.keys())
    values = list(param_grid.values())
    all_results = []
    best_value = -np.inf
    best_params = {}

    for combo in product(*values):
        params = dict(zip(keys, combo, strict=False))
        result = _evaluate_combo(df, config, metric, params)
        if result is None:
            continue
        result_entry, metric_value = result
        all_results.append(result_entry)
        if metric_value > best_value:
            best_value = metric_value
            best_params = params

    return {
        "best_params": best_params,
        f"best_{metric}": round(best_value, 4),
        "all_results": all_results,
    }


def format_backtest_result(result: BacktestResult) -> str:
    """Format backtest result as a readable markdown string."""
    lines = [
        f"## Backtest: {result.symbol} ({result.strategy})",
        f"**Period:** {result.period}",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| CAGR | {result.cagr:.2%} |",
        f"| Sharpe Ratio | {result.sharpe_ratio:.2f} |",
        f"| Sortino Ratio | {result.sortino_ratio:.2f} |",
        f"| Calmar Ratio | {result.calmar_ratio:.2f} |",
        f"| Max Drawdown | {result.max_drawdown:.2%} |",
        f"| Max Drawdown Duration | {result.max_drawdown_duration_days} days |",
        f"| Win Rate | {result.win_rate:.2%} |",
        f"| Total Trades | {result.total_trades} |",
        f"| Profit Factor | {result.profit_factor:.2f} |",
        f"| Total Return | {result.total_return:.2%} |",
        f"| Annualized Volatility | {result.annualized_volatility:.2%} |",
    ]
    return "\n".join(lines)

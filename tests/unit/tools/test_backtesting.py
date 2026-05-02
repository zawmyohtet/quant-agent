"""Tests for backtesting tools."""
from __future__ import annotations

import pandas as pd

from quantagent.tools.backtesting import BacktestResult


def test_backtest_result_model():
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

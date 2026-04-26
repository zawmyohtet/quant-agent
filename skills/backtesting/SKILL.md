---
name: backtesting
description: >
  Use this skill when the user asks to backtest a strategy, evaluate historical
  performance, compare strategies, interpret Sharpe ratio or drawdown, validate
  a strategy's statistical reliability, or run walk-forward analysis. Also use
  when recommending any systematic trading strategy that should be validated
  against historical data before being proposed.
license: MIT
metadata:
  author: quantagent
  version: "1.0"
allowed-tools: run_backtest, get_ohlcv_data
---

# Backtesting

## Overview
This skill defines how to run, interpret, and validate backtests using QuantAgent's
backtesting engine. Always follow this methodology before recommending any systematic strategy.

## When to Run a Backtest
- The user asks "does this strategy work?" or "what's the historical return of X?"
- You are about to recommend a trend-following or mean-reversion strategy
- The user wants to compare two strategies head to head
- Always backtest before recommending — never rely on indicator readings alone

## Step-by-Step Methodology

### 1. Establish a baseline
Always run buy_and_hold first on the same symbol and period.
Every strategy must beat buy-and-hold on risk-adjusted basis (Sharpe) to be worth using.

### 2. Run the candidate strategy
Use run_backtest with the user's requested strategy and a minimum 5-year period.
Shorter periods are unreliable — flag this to the user if they request < 2y.

### 3. Check statistical reliability
Total trades must be >= 30. Fewer trades means the result is statistically insignificant.
If < 30 trades, state this explicitly and lengthen the period or loosen entry conditions.

### 4. Walk-forward validation for strong results
If Sharpe > 1.5, run walk-forward (n_splits=5) to check for overfitting.
Out-of-sample Sharpe degradation > 40% vs in-sample is a red flag for overfitting.

### 5. Report interpretation thresholds

| Metric | Acceptable | Good | Exceptional |
|---|---|---|---|
| Sharpe ratio | > 1.0 | > 1.5 | > 2.0 |
| Max drawdown | < 25% | < 15% | < 10% |
| Win rate | > 45% | > 55% | > 65% |
| Profit factor | > 1.3 | > 1.5 | > 2.0 |

Always report: CAGR, Sharpe, Sortino, Max Drawdown, Win Rate, Total Trades, Profit Factor.

## Supporting files
- strategy_templates.md — parameter defaults for each built-in strategy

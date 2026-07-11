---
name: strategy-patterns
description: >
  Use this skill when the user asks which strategy to use, how to build a trading
  system, how to select between trend-following and mean-reversion, what works in
  the current market regime, or when designing an entry/exit/stop framework for
  any equity or ETF. Also use when the user describes market conditions and wants
  a structured approach.
license: MIT
metadata:
  author: quantagent
  version: "1.0"
allowed-tools: compute_technical_indicators, run_backtest_tool, get_ohlcv_data
---

# Strategy Patterns

## Overview
Strategy selection must always start with regime detection. A strategy that works
in a trending market will fail in a ranging one. This skill defines the selection
logic and the canonical entry/exit/stop templates for each regime.

## Step 1: Classify the Regime
1. Fetch 1y OHLCV, compute ADX(14) and SMA(200)
2. Check current VIX level (via get_economic_indicators)
3. Classify:

| Condition | Regime |
|---|---|
| ADX > 25 + price > SMA(200) | Bull trend |
| ADX > 25 + price < SMA(200) | Bear trend |
| ADX < 20 | Ranging |
| VIX > 25 | High volatility (reduce size, avoid new entries) |

## Step 2: Select Strategy

| Regime | Recommended | Baseline |
|---|---|---|
| Bull trend | sma_crossover, macd_momentum | buy_and_hold |
| Bear trend | Defensive / inverse ETF | Cash |
| Ranging | rsi_mean_reversion | buy_and_hold |
| High vol | Reduce position size only | buy_and_hold |

## Strategy Templates

### Trend-Following (Bull Regime)
Entry: EMA(12) crosses above EMA(26) + ADX > 25 + price > SMA(200)
Exit: EMA(12) crosses below EMA(26) OR price drops 2×ATR(14) from high
Stop: 2×ATR(14) below entry

### RSI Mean-Reversion (Ranging Regime)
Entry: RSI(14) < 30 + price at or below lower Bollinger Band(20,2)
Exit: RSI(14) > 55 OR price reaches middle Bollinger Band
Stop: Below recent 10-day swing low

### MACD Momentum (Trending Only)
Entry: MACD line crosses above signal line + histogram turning positive + ADX > 20
Exit: MACD line crosses below signal line
Stop: Below EMA(26) at entry bar

## Reporting Format
For any strategy recommendation, state:
1. Regime classification and evidence (ADX value, price vs SMA200)
2. Strategy selected and why
3. Specific entry condition (exact indicator values)
4. Exit condition
5. Stop-loss level in both % and dollar terms
6. Backtest summary (must be run before finalizing recommendation)

## Supporting files
- regime_matrix.md — extended regime classification matrix with edge cases

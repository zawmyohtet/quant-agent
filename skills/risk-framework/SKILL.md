---
name: risk-framework
description: >
  Use this skill when the user asks about position sizing, stop-loss levels, portfolio
  risk, VaR, drawdown limits, risk/reward ratios, or when you are about to recommend
  an entry point for any trade. Always apply this skill before stating a specific
  price target, stop, or position size.
license: MIT
metadata:
  author: quantagent
  version: "1.0"
allowed-tools: compute_portfolio_metrics, run_backtest
---

# Risk Framework

## Overview
Every trade recommendation must include a stop-loss level and a position size.
Never recommend an entry without both. This skill defines the standard methodology.

## Stop-Loss Placement

### Trend strategies
Stop = entry price - (2 x ATR(14))
Always use ATR-based stops for trend-following; fixed-percentage stops ignore volatility.

### Mean-reversion strategies
Stop = most recent swing low (for longs) or swing high (for shorts).
Confirm the swing level is within 7% of entry — wider stops require smaller position size.

## Position Sizing

Apply half-Kelly as a ceiling, capped at 10% of portfolio:
```
win_rate and profit_factor come from the backtest result.
f = win_rate - (1 - win_rate) / profit_factor   # Kelly fraction
recommended_size = min(f * 0.5, 0.10)           # Half-Kelly, 10% cap
```
Always express in both percentage and dollar terms.
Example: "3.2% of portfolio = $3,200 on a $100k account."

## Key Risk Metrics to Always Report
- Max Drawdown: from backtest; flag if > 25%
- VaR(95%): maximum expected daily loss 95% of the time
- Beta: flag if |beta| > 1.5 (high market sensitivity)
- Risk/Reward: minimum acceptable ratio is 1:2 (risk $1 to make $2)

## Portfolio-Level Rules
- Max single position: 10% unless user explicitly overrides
- Max sector concentration: 30%
- High-volatility regime (VIX > 25): reduce all position sizes by 50%

## Supporting files
- position_sizing.md — worked examples of Kelly sizing across different win rates

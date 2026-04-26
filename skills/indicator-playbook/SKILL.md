---
name: indicator-playbook
description: >
  Use this skill when computing or interpreting technical indicators: RSI, MACD,
  Bollinger Bands, moving averages, ATR, ADX, Stochastic, OBV, VWAP, or any
  other indicator. Also use when deciding which indicators are appropriate for the
  current market regime or when the user asks why a specific indicator gave a
  false signal.
license: MIT
metadata:
  author: quantagent
  version: "1.0"
allowed-tools: compute_technical_indicators, detect_chart_patterns
---

# Indicator Playbook

## Overview
Indicators are tools, not signals. Always combine them; never rely on a single indicator.
This skill defines when to use each indicator and how to interpret readings correctly.

## Regime Detection First
Before selecting indicators, classify the market regime:
- Run ADX(14): ADX > 25 → trending; ADX < 20 → ranging
- Compare price vs SMA(200): above = bull bias, below = bear bias
- Check VIX level: > 25 = high volatility regime

## Indicator Selection by Regime

| Regime | Primary | Secondary | Avoid |
|---|---|---|---|
| Trending | SMA/EMA crossover, MACD | ADX, ATR | RSI extremes, Stochastic |
| Ranging | RSI, Stochastic | Bollinger Bands | MACD, moving averages |
| High vol | ATR (size only) | Bollinger Bands | All momentum |

## Indicator Reference

### Trend
- SMA(50)/SMA(200): regime detection; golden cross (50 > 200) = bull; death cross = bear
- EMA(12)/EMA(26): faster; use for swing trade entries
- ADX(14): strength gauge; > 25 trending, < 20 ranging; direction from +DI/-DI

### Momentum
- RSI(14): overbought > 70, oversold < 30; divergence more reliable than level alone
- MACD(12,26,9): histogram direction > crossover timing; only valid in trending markets
- Stochastic(14,3): best in ranging markets; use %K/%D crossover near extremes only

### Volatility
- Bollinger Bands(20,2): squeeze → breakout; walk-the-band in strong trends
- ATR(14): volatility unit for stop-loss placement and position sizing

### Volume
- OBV: confirm price moves; OBV diverging from price is an early warning signal
- VWAP: intraday fair value; daily chart use is limited to high-volume stocks

## Combination Rules
Never use more than two indicators from the same category.
Standard combination: one trend + one momentum + one volume indicator.

## Supporting files
- indicator_combos.md — tested indicator combinations by market regime

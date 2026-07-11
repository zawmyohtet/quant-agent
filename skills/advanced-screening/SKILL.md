---
name: advanced-screening
description: >
  Use this skill when the user asks to screen or scan for stocks with
  specific criteria — value screens, momentum screens, oversold bounces,
  breakout setups, VCP/Minervini patterns, or combined fundamental and
  technical filters. Also use when managing custom screening universes.
license: MIT
metadata:
  author: quantagent
  version: "1.0"
allowed-tools: screen_stocks_tool, screen_technicals_tool, screen_combined_tool, screen_vcp_tool, screen_breakouts_tool, screen_oversold_tool, list_universes_tool, create_universe_tool, detect_market_regime
---

# Advanced Screening

## Overview
Translate the user's intent into the right screener and criteria, run it,
and present ranked candidates with the reasoning behind each filter.
Screens are idea *generators* — always frame results as candidates for
further analysis, not buy lists.

## Choosing the Screener

| User intent | Tool | Typical criteria |
|---|---|---|
| Cheap/quality stocks | `screen_stocks_tool` | pe_lt, pb_lt, roe_gt, debt_equity_lt, dividend_yield_gt |
| Momentum/trend | `screen_technicals_tool` | price_above_sma: 200, macd_bullish, adx_gt: 25 |
| Quality + timing | `screen_combined_tool` | fundamentals first, then technicals |
| Pre-breakout bases | `screen_vcp_tool` | defaults are Minervini-calibrated |
| New-high momentum | `screen_breakouts_tool` | proximity 5%, volume 1.5x |
| Contrarian bounce | `screen_oversold_tool` | rsi 30, 20% decline, reversal bar |

## Criteria Construction Rules

- Start loose, tighten iteratively: 0 results means over-filtering, not
  "nothing works". Drop the most restrictive criterion first.
- Growth/value units are decimals (roe_gt: 0.15 = 15% ROE); market cap in
  dollars (mcap_gt: 1e10 = $10B).
- Combine at most 3-4 criteria — every additional filter biases toward
  data artifacts.
- Universe-scale screens are slow on the free tier (a full S&P 500
  technical screen batch-downloads a year of data). Warn on first use.

## Regime Context (always)

Check `detect_market_regime` before presenting long candidates. Breakout
and VCP screens perform poorly in bear regimes; oversold-reversal screens
are dangerous in strong downtrends (falling knives). Say so when the
regime disagrees with the screen type.

## Custom Universes

Users can screen their own lists: `create_universe_tool` with a name and
symbols, then pass the name as the universe. Built-ins: sp500, nasdaq100,
dow30, sector_etfs. Russell 2000 is unavailable (no free constituent
source).

## How to Report

1. State the screen, universe, and criteria used (so it's reproducible).
2. Present candidates in a table: symbol, price, and the metrics that
   drove inclusion.
3. Flag the regime context and any screen-specific caveats.
4. Offer the natural next step: deep-dive analysis on 1-3 names.

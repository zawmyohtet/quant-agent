---
name: market-breadth
description: >
  Use this skill when the user asks about market breadth, advance/decline,
  new highs and lows, breadth thrust, market participation, whether a rally
  is broad or narrow, or divergences between the index and its constituents.
license: MIT
metadata:
  author: quantagent
  version: "1.0"
allowed-tools: compute_advance_decline, compute_new_highs_lows, compute_breadth_thrust, compute_percent_above_ma, warm_breadth_cache, count_distribution_days, detect_follow_through_day
---

# Market Breadth Analysis

## Overview
Breadth measures how many stocks participate in a move. Indexes are
cap-weighted, so a handful of mega-caps can mask broad deterioration —
breadth divergences are among the earliest warning signals available.

## Data Requirement (important)
Universe-level breadth reads a local cache. If a breadth tool reports no
data or a proxy flag, tell the user the first computation needs a one-time
warm-up (up to ~10 minutes for the S&P 500) and offer to run
`warm_breadth_cache`. After that, updates are incremental and fast. The
`sector_etfs` universe always works instantly and is a reasonable proxy.

## Indicators and Interpretation

- **Advance/Decline line** (`compute_advance_decline`): cumulative net
  advancers. The signal is *divergence*: index making new highs while the
  A/D line does not = narrowing leadership, late-stage rally. A/D
  confirming new highs = healthy trend.
- **New highs/lows** (`compute_new_highs_lows`): expansion of 52-week
  lows while the index is near highs is a classic top warning
  (Hindenburg-style). HighLowRatio > 0.7 = healthy; < 0.3 = stress.
- **Percent above MA** (`compute_percent_above_ma`): >70% above the
  200-day = broad bull (watch for overbought >90%); <30% = washed out,
  often near capitulation lows. The 50-day version swings faster and
  marks tactical extremes.
- **Breadth thrust** (`compute_breadth_thrust`): oscillator above +50 =
  bullish thrust (powerful initiation signal off lows, especially with a
  Follow-Through Day); below -50 = intense selling.

## Reading Combinations

| A/D line | New lows | % above 200MA | Reading |
|---|---|---|---|
| New highs | Contracting | Rising >60% | Healthy bull — confirm exposure |
| Flat/falling vs index highs | Expanding | Falling <50% | Divergence — reduce risk |
| Falling hard | Spiking | <25% | Capitulation zone — watch for thrust + FTD |

## How to Report

1. State whether breadth confirms or diverges from the index — that is
   the headline.
2. Give the two or three most decisive numbers (A/D trend, net new
   highs, % above 200MA), not every series.
3. Tie the conclusion to exposure: divergence = trim into strength;
   thrust after washout = start rebuilding.
4. Note the data source (full universe vs sector-ETF proxy) when a proxy
   was used.

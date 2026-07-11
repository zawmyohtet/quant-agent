---
name: sector-rotation
description: >
  Use this skill when the user asks about sector rotation, which sectors are
  leading or lagging, sector relative strength, where we are in the economic
  cycle, or which sector to overweight. Also use when ranking sectors or
  analyzing a specific sector's context.
license: MIT
metadata:
  author: quantagent
  version: "1.0"
allowed-tools: detect_sector_rotation, get_sector_performance_ranked, compute_sector_relative_strength, get_industry_performance
---

# Sector Rotation Analysis

## Overview
Sector leadership rotates ahead of the economic cycle. Reading the rotation
tells you (a) the market's macro expectation and (b) where new longs have a
tailwind. Use `detect_sector_rotation` for the pattern,
`get_sector_performance_ranked` for the raw ranking, and
`compute_sector_relative_strength` for benchmark-relative trends.

## Methodology

- **Relative strength (RS)**, not absolute return, is the unit of analysis:
  RS = sector return / SPY return over the window. RS > 1 is leadership.
- **RS momentum** (change in RS over half the lookback) separates
  *improving* sectors (accumulate early) from merely *extended* leaders.
- **Risk-on vs risk-off**: average RS momentum of cyclical sectors
  (Tech, Discretionary, Financials, Industrials, Materials, Communication,
  Energy, Real Estate) minus defensive sectors (Staples, Utilities,
  Healthcare). Positive spread = risk-on rotation.

## Cycle Phase Mapping

Leadership groups map to economic cycle phases:

| Phase | Typical leaders |
|---|---|
| early-recovery | Financials, Consumer Discretionary, Real Estate, Industrials |
| mid-expansion | Technology, Communication Services, Industrials |
| late-cycle | Energy, Materials, Consumer Staples, Healthcare |
| recession | Utilities, Consumer Staples, Healthcare |

Treat the phase estimate as context, not a forecast — rotation can be noise
over short windows. Confirm with at least a 1-month and a 3-month view
before calling a phase change.

## How to Report

1. Lead with the rotation signal (risk-on/risk-off/neutral) and cycle phase.
2. Name leading, improving, and deteriorating sectors — improving sectors
   are usually the actionable list.
3. For a specific sector question, give its RS ratio, rank, trend, and top
   industries (`get_industry_performance`; warn that industry drill-down is
   slow on first use).
4. Cross-check with the market regime: sector longs in a bear regime need
   smaller size regardless of relative strength.

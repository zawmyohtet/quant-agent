---
name: pair-trading
description: >
  Use this skill when the user asks about pair trading, statistical
  arbitrage, cointegrated pairs, spread trading, hedge ratios, or
  market-neutral strategies.
license: MIT
metadata:
  author: quantagent
  version: "1.0"
allowed-tools: find_cointegrated_pairs, compute_spread_metrics, run_backtest, detect_market_regime
---

# Pair Trading / Statistical Arbitrage

## Overview
A pair trade is long one leg, short the other, betting the *spread*
mean-reverts. The edge comes from cointegration — a stationary long-run
relationship — not from correlation. Two stocks can be 0.95 correlated
and still drift apart forever.

## Methodology

1. **Scan within a sector** (`find_cointegrated_pairs` with a sector
   filter). Cross-sector "pairs" that pass the test are usually
   statistical accidents; economic linkage (same industry, shared
   inputs, substitute products) is what makes the relationship durable.
2. **Validate the pair** (`compute_spread_metrics`):
   - `coint_pvalue` < 0.05 — the Engle-Granger gate.
   - `half_life_days` — expected mean-reversion speed. 5–30 days is
     tradeable; None or 60+ means the spread doesn't revert usefully.
   - `hedge_ratio` — units of leg B per unit of leg A for a
     dollar-neutral-ish spread. Recompute periodically; it drifts.
3. **Trade the z-score**: enter at |z| ≥ 2 in the stated direction,
   exit near z = 0 (|z| ≤ 0.5), hard stop at |z| ≥ 3–4 — a spread that
   keeps widening past 3σ is telling you the relationship broke.

## Risks to State Every Time

- **Regime breaks kill pairs**: mergers, guidance resets, index
  add/drops, or one leg's fundamental story changing. A p-value from
  the past year cannot see these coming. Check recent news on both legs.
- The p-value is in-sample; with ~1,700 pairs tested at 0.05, dozens
  pass by chance. Prefer pairs that are also economically obvious.
- Shorting has borrow costs and squeeze risk that this analysis ignores.
- Size both legs by the hedge ratio, and treat the *pair* as one
  position in journal/risk-gate terms (one thesis, one stop in z-terms).

## How to Report

1. Lead with the strongest 2–3 pairs: symbols, p-value, half-life, and
   current z-score with the entry/exit signal.
2. State the trade construction explicitly (long X shares-equivalent,
   short hedge_ratio × Y).
3. Note in-sample and regime-break caveats — always.

---
name: market-regime
description: >
  Use this skill when the user asks about the current market regime, market
  health, whether it's a bull or bear market, how much equity exposure to
  hold, whether now is a good time to buy, or asks for a market overview.
  Also use before recommending any new position, to set exposure context.
license: MIT
metadata:
  author: quantagent
  version: "1.0"
allowed-tools: detect_market_regime, get_market_summary, count_distribution_days, detect_follow_through_day, get_economic_indicators
---

# Market Regime Detection

## Overview
Market regime is the single most important context for every trade decision.
Detect it with `detect_market_regime` (or `get_market_summary` for the full
picture) and always translate the result into an exposure recommendation —
never describe the regime without saying what it means for position sizing.

## Methodology

The regime score (0-100) is a weighted composite of nine components:

1. **Cross-asset ratios (50%)** — each scored from its 3-month trend:
   - RSP/SPY: equal-weight vs cap-weight. Rising = broad participation
     (healthy); falling = narrow, concentration-driven market (fragile).
   - IWM/SPY: small caps leading = risk appetite; lagging = defensive tape.
   - XLY/XLP: cyclicals vs staples. The classic risk-on/risk-off ratio.
   - SPY/TLT: stocks vs long bonds. Also watch the stock-bond correlation —
     a persistently positive correlation flags an inflation-driven regime
     where bonds no longer hedge equities.
   - HYG/LQD: junk vs investment-grade credit. Credit stress leads equity
     stress; a falling ratio is an early warning.
2. **Index trend (20%)** — SPY vs its 50 and 200 SMAs.
3. **Volatility (10%)** — VIX bands: <15 calm, 15-20 normal, 20-25 elevated,
   25-30 stressed, >30 crisis.
4. **Breadth proxy (10%)** — percent of sector ETFs above their 50 SMA.
5. **Sector participation (10%)** — percent of sectors with positive 1-month
   returns.

## Regime Labels and Exposure Bands

| Score | Regime | Recommended equity exposure |
|---|---|---|
| 80-100 | strong-bull | 90-100% |
| 60-79 | bull | 70-90% |
| 40-59 | neutral | 50-70% |
| 20-39 | bear | 40-60% |
| 0-19 | strong-bear | 25-40% |

The `confidence` field is the fraction of components agreeing with the
composite direction. Below 0.6, describe the regime as "mixed" and lean
toward the conservative end of the exposure band.

## Timing Signals

Complement the regime with O'Neil-style timing:
- `count_distribution_days`: 5+ distribution days in 25 sessions = market
  under pressure; tighten stops and stop adding exposure even in a bull
  regime.
- `detect_follow_through_day`: after a correction, do not call a bottom
  until a Follow-Through Day confirms (day 4+ of rally, +1.25% on higher
  volume). "rally-attempt" status is unconfirmed — say so.

## How to Report

1. State the regime label, score, and confidence in one sentence.
2. State the recommended exposure band explicitly.
3. Note the strongest supporting and strongest contradicting component.
4. If timing signals disagree with the regime (e.g. bull regime but 5
   distribution days), surface the tension — deteriorating timing inside a
   bull regime is how tops start.
5. Never predict; describe conditions and the exposure that fits them.

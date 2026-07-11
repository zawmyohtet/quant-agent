---
name: earnings-analysis
description: >
  Use this skill when the user asks how a stock behaves around earnings,
  wants an earnings calendar, is planning a trade into or after an
  earnings report, or mentions post-earnings drift (PEAD).
license: MIT
metadata:
  author: quantagent
  version: "1.0"
allowed-tools: analyze_earnings_impact, get_earnings_calendar_range, get_stock_news, journal_log_trade, check_trade_discipline
---

# Earnings Event Analysis

## Overview
Earnings are scheduled volatility events. The job is never to predict a
print — it is to size expectations from how the stock has *historically*
reacted, and to separate the day-1 gamble from the tradeable aftermath.

## Reading `analyze_earnings_impact`

- **avg_abs_day1_move** — the historical "expected move". Any position
  held through the report should be sized so this move is survivable.
  If the user has options context, compare it to the implied move:
  implied >> historical suggests rich premiums, and vice versa.
- **positive_rate** — 8 events is a small sample; treat 5/8 vs 3/8 as
  noise, not signal. Say so.
- **avg_gap vs avg_day1_move** — a big gap that fades by the close
  (gap > day1) means the initial reaction routinely overshoots.
- **drift_5d / drift_20d** — post-earnings-announcement drift. Positive
  average drift after positive surprises is the PEAD effect: the
  higher-quality trade is often *after* the print, in the drift
  direction, rather than holding through the event.

## Calendar Workflow

`get_earnings_calendar_range` for "who reports next week" questions —
prefer explicit symbols (fast) over whole universes (slow first time,
12h cache). Cross-reference open journal positions: flag any active
trade with a report inside its expected holding period.

## Discipline Rules

- Holding a position through earnings is a distinct decision: the stop
  does not protect against a gap. Say this explicitly and suggest
  reducing size to what the historical abs move allows.
- Earnings trades still go through the journal + discipline gate; the
  thesis must state whether the trade is *into* the print (volatility
  bet) or *after* it (drift/reaction bet).
- Never extrapolate a "beat streak" into a prediction for the next
  report.

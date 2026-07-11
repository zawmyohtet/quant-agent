---
name: report-generation
description: >
  Use this skill when the user asks for a report, brief, summary document,
  or export — daily market brief, sector report, stock deep-dive, portfolio
  review, or screening results — especially when they want it saved to a
  file or in HTML.
license: MIT
metadata:
  author: quantagent
  version: "1.0"
allowed-tools: generate_report_tool, get_market_summary, detect_market_regime
---

# Report Generation

## Overview
`generate_report_tool` produces structured reports, saves them under
`~/.quantagent/reports/`, and returns the file path plus a preview.
Use it whenever the user wants a *document* rather than a conversational
answer.

## Report Types

| Type | Target argument | Contents |
|---|---|---|
| `market` | (none) | Indices, regime + exposure band, timing signals, breadth, sentiment, sector ranking, rotation, top movers |
| `sector` | Sector name (e.g. `Technology`) | Performance, relative strength, rotation context, ETF technicals, industry breakdown |
| `stock` | Ticker (e.g. `AAPL`) | Overview, technicals, key levels, patterns, fundamentals, news |
| `portfolio` | Comma-separated tickers | Allocation, risk metrics, sector exposure, max-Sharpe suggestion, Monte Carlo |
| `screening` | Screen type (`fundamental`/`technical`/`vcp`/`breakout`/`oversold`) + `criteria` JSON | Parameters, results table, caveats |

Formats: `markdown` (default) or `html` (styled, printable).

## Guidelines

- Tell the user the saved file path — that's the deliverable.
- After generating, summarize the 3-5 most decision-relevant findings in
  chat; don't paste the whole report.
- Sections degrade gracefully: if one shows "Data unavailable", mention it
  and (if it's the top-movers/breadth section) offer `warm_breadth_cache`.
- Sector names must be one of the 11 GICS sectors; portfolio weights are
  equal-weight unless the user gives weights (then explain the
  normalization).
- Reports state facts and computed suggestions — never present the
  optimization output as advice.

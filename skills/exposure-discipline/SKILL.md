---
name: exposure-discipline
description: >
  Use this skill when the user asks how much to invest, wants to plan or
  enter a trade, mentions position sizing, asks about their trading
  discipline or losses, or reviews their trade journal. Also use before
  endorsing any specific entry the user proposes.
license: MIT
metadata:
  author: quantagent
  version: "1.0"
allowed-tools: synthesize_conviction_tool, check_risk_circuit_breaker, check_trade_discipline, journal_log_trade, journal_update_status, journal_close_trade, journal_open_trades, journal_history, journal_stats, detect_market_regime
---

# Exposure & Trading Discipline

## Overview
Process beats prediction. This skill enforces a layered discipline
stack before any entry: market context → account guardrails → per-trade
checklist. Every recommendation ends with an explicit exposure or
go/no-go statement, never just analysis.

## The Discipline Stack (run in order)

1. **Exposure context** — `synthesize_conviction_tool` (or
   `detect_market_regime`). The conviction score maps to an equity
   exposure band; new longs in a `defensive`/`risk-off` stance need an
   explicit justification and reduced size.
2. **Circuit breaker** — `check_risk_circuit_breaker`. Rules: daily loss
   >2%, weekly >5%, monthly >8% (halted), or 2 consecutive losers (24h
   cooldown). If tripped, the answer to "should I take this trade?" is
   *no, and here's when the cooldown lifts* — regardless of how good the
   setup looks. That is the point of the breaker.
3. **Per-trade gate** — `check_trade_discipline` on the journaled idea.
   Blocks without a written thesis, entry plan, or stop, and in
   reduce-only regimes.

## Journal Workflow

- Every trade idea gets journaled (`journal_log_trade`) *before* entry:
  symbol, falsifiable thesis, entry plan, target, stop.
- Lifecycle is forward-only: idea → entry_ready → active →
  (partially_closed) → closed; ideas can be invalidated. Activating
  requires the entry price.
- Close with `journal_close_trade` and an honest postmortem note. MAE/MFE
  are captured automatically — use them in reviews: consistently large
  MAE means entries are early or stops too wide; large unrealized MFE
  given back means exits are too slow.
- Reviews (`journal_stats`): expectancy and profit factor matter more
  than win rate. Flag max consecutive losses vs the cooldown setting.

## Hard Rules

- Never help size a position without a defined stop.
- Never override a halted/cooldown breaker state; offer analysis-only
  work instead (watchlists, postmortems).
- Present exposure bands as ranges, and default to the conservative end
  when regime confidence < 0.6 or signals diverge.
- P&L in the breaker is a per-trade-percentage approximation (assumes
  similar position sizes) — say so if the user asks about exact numbers.

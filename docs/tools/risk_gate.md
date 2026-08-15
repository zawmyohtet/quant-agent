# Risk Gate

Source: `quantagent/tools/risk_gate.py`

A behavioral risk-gating stack (adapted from claude-trading-skills) with two
parts: a **circuit breaker** that halts new entries after account-level
losses or losing streaks, and a **pre-trade discipline gate** that blocks a
journaled trade idea that lacks a plan, a stop, or is fighting the market
regime.

Both gates only ever **emit recommendations** — neither one holds a broker
connection or has any way to cancel/place an order. They read the trade
journal (`quantagent.tools.trade_journal`) and market breadth
(`quantagent.tools.market_breadth.detect_market_regime`) and return a
verdict for a human or the calling agent to act on.

**P&L approximation caveat (from the module docstring):** period P&L is
computed by summing per-trade `realized_pnl_pct` values from the journal —
this assumes roughly equal-sized positions across trades. It's a
behavioral-guardrail signal, not an accounting-grade P&L statement.

---

## CircuitBreakerConfig

**Agent-facing tool name:** Not exposed as an agent tool directly (it's the
optional config object passed into `check_circuit_breaker` /
`check_discipline_gate`; agent-facing tools use the frozen defaults).

**Purpose:** Defines the loss-limit and losing-streak thresholds that decide
when new trading should pause — the tunable knobs behind the circuit
breaker.

**Why built this way:** A frozen (`model_config = ConfigDict(frozen=True)`)
pydantic model — the config is immutable once constructed, so a single
`CircuitBreakerConfig()` instance can be safely reused/passed around without
risk of a caller mutating shared thresholds mid-evaluation.

**Math (exact defaults):**
| Field | Default | Meaning |
|---|---|---|
| `daily_loss_limit_pct` | `2.0` | Trip if today's realized P&L ≤ -2% |
| `weekly_loss_limit_pct` | `5.0` | Trip if this week's realized P&L ≤ -5% |
| `monthly_loss_limit_pct` | `8.0` | Trip if this month's realized P&L ≤ -8% |
| `consecutive_loss_cooldown` | `2` | 2+ consecutive closed losses triggers a cooldown |
| `cooldown_hours` | `24` | Cooldown lasts 24h from the most recent loss's close time |

**Usage:** Construct with any subset of overrides, e.g.
`CircuitBreakerConfig(daily_loss_limit_pct=1.0)`; unset fields keep the
defaults above. Pass to `check_circuit_breaker(config=...)` or
`check_discipline_gate(provider, trade_id, config=...)`.

---

## check_circuit_breaker

**Agent-facing tool name:** `check_risk_circuit_breaker`

**Purpose:** Answers "should I even be looking for new trades right now?" by
checking realized journal P&L against daily/weekly/monthly drawdown limits
and recent losing streaks — the account-level guardrail that exists to stop
a trader (or agent) from revenge-trading through a bad stretch.

**Why built this way:** Reads the last 40 days of *closed* trades
(`get_trade_history(days=40, status="closed")`) — wide enough to cover a
full month lookback with margin. An empty journal naturally defaults to
`trading_allowed` (all period P&L sums to 0, nothing trips). Loss-limit
breaches (`halted`) are checked and reported before the losing-streak
cooldown, and take priority: `cooldown` is only evaluated `if not
triggered`, so a halted state is never masked by a milder cooldown message.
The cooldown itself only fires if the streak's cooldown window
(`last_loss_at + cooldown_hours`) hasn't already elapsed (`until > now`) —
an old losing streak with no recent trades doesn't perpetually block new
entries.

**Math:**
- **Period P&L** (`_period_pnl`): for each period boundary `since`, sums
  `realized_pnl_pct * 100` (converted to a percentage) over closed trades
  where `closed_at >= since`, rounded to 4 decimals.
  - `daily_pct`: `since = now - 1 day`
  - `weekly_pct`: `since = now - 7 days`
  - `monthly_pct`: `since = now - 31 days`
- **Triggered rules** (`_triggered_rules`): for each `(period, limit)` pair,
  triggers if `period_pnl[period] <= -limit` (i.e. losses at or beyond the
  limit, not just approaching it). Produces a message like `"daily loss
  3.5% exceeds 2.0% limit"`.
- **State** = `"halted"` if any loss-limit rule is triggered; else
  `"trading_allowed"`, downgraded to `"cooldown"` if the streak condition
  below fires.
- **Consecutive-loss streak** (`_consecutive_losses`): sorts closed trades
  with a recorded P&L by `closed_at` ascending, then walks them
  incrementing a running streak on each `realized_pnl_pct <= 0` and
  **resetting to 0** on any win (`> 0`) — so it's the *current* losing
  streak, not the historical max. Returns `(streak, last_loss_at)` where
  `last_loss_at` is the close time of the most recent loss (or `None` if
  the streak is currently 0).
- **Cooldown trigger**: fires when `streak >= consecutive_loss_cooldown`
  (default 2) **and** `last_loss_at + cooldown_hours` (default 24h) is still
  in the future. `cooldown_until` is that timestamp, ISO-formatted.

**Usage:**
- Params: `config: CircuitBreakerConfig | None = None` (defaults applied if
  omitted).
- Returns: `dict` — `{state: "trading_allowed" | "cooldown" | "halted",
  triggered_rules: list[str], cooldown_until: str | None, period_pnl:
  {daily_pct, weekly_pct, monthly_pct}}`.
- Example:
  ```python
  result = await check_circuit_breaker()
  # {"state": "cooldown", "triggered_rules":
  #    ["2 consecutive losses — cooldown for 24h after the last loss"],
  #  "cooldown_until": "2026-08-16T09:15:00+00:00",
  #  "period_pnl": {"daily_pct": -1.2, "weekly_pct": -3.4, "monthly_pct": -3.4}}
  ```

---

## check_discipline_gate

**Agent-facing tool name:** `check_trade_discipline` (provider-bound wrapper
`_check_trade_discipline` in `tools_registry.py`, registered via
`_bind_provider`)

**Purpose:** The pre-trade checklist — validates one specific journaled
trade idea against the rules a disciplined trader should never skip: is
there a written thesis and plan, is there a stop, and is the broader account
or market environment telling you to sit this one out. Meant to be run
before advancing a trade to `entry_ready` or `active`.

**Why built this way:** Composes the other two checks (`check_circuit_
breaker` and `detect_market_regime`) rather than duplicating their logic —
the discipline gate is a single aggregation point so an agent only needs one
call before acting on a trade idea. Every check returns a uniform
`{passed, detail}` shape (`_check` helper) so the result is easy to render
and the failure reason is always human-readable. It imports `_connect` and
`_load_trade` directly from `trade_journal` (rather than a public journal
function) purely to fetch the raw trade record without going through the
lifecycle-transition machinery — this is a read, not a status change.

**Math:** No numeric formulas of its own; it's a validation aggregator over:
1. **`written_thesis`** — passes if `trade.thesis.strip()` is non-empty.
2. **`entry_plan`** — passes if `trade.entry_plan.strip()` is non-empty.
3. **`stop_defined`** — passes if `trade.stop is not None`.
4. **`circuit_breaker`** — passes if `check_circuit_breaker(config)["state"]
   == "trading_allowed"` (fails on both `"cooldown"` and `"halted"`).
5. **`market_regime`** — passes if `detect_market_regime(provider)["regime"]`
   is **not** in `_REDUCE_ONLY_REGIMES = {"bear", "strong-bear"}`. The detail
   string also surfaces the regime's recommended exposure range (`min_pct`–
   `max_pct`).

Overall `result` is `"pass"` only if **all five** checks pass; any single
failure makes it `"blocked"`.

**Usage:**
- Params: `provider: AbstractDataProvider`, `trade_id: str`, `config:
  CircuitBreakerConfig | None = None`.
- Returns: `dict` — `{result: "pass" | "blocked", trade_id: str, checks:
  {written_thesis, entry_plan, stop_defined, circuit_breaker,
  market_regime: {passed: bool, detail: str}}}`.
- Example:
  ```python
  gate = await check_discipline_gate(provider, trade_id="a1b2c3d4e5f6")
  # {"result": "blocked", "trade_id": "a1b2c3d4e5f6",
  #  "checks": {
  #    "written_thesis": {"passed": True, "detail": "Breaking out ..."},
  #    "entry_plan": {"passed": True, "detail": "Buy on close above 135 ..."},
  #    "stop_defined": {"passed": False, "detail": "no stop"},
  #    "circuit_breaker": {"passed": True, "detail": "state=trading_allowed"},
  #    "market_regime": {"passed": True,
  #        "detail": "regime=neutral (exposure 40-70%)"}}}
  ```

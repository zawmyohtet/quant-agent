# Risk Gate Tools

`quantagent/tools/risk_gate.py`

Tools for enforcing trading discipline and preventing emotional decisions. These are behavioral guardrails that help you (or the agent) avoid common trading mistakes like revenge-trading after losses, trading without a plan, or fighting the market regime.

Both gates only **emit recommendations** — they don't place or cancel orders. They read your trade journal and the current market regime, then return a verdict for you to act on.

---

## check_circuit_breaker

**Agent tool:** `check_risk_circuit_breaker`

Answers the question: "Should I even be looking for new trades right now?"

### What It Does

Checks your recent trading performance against loss limits and losing streak thresholds. If you've hit a daily/weekly/monthly loss limit or had too many consecutive losses, it tells you to step back and cool off.

This is the trading equivalent of a circuit breaker in an electrical system — when things get too hot, it trips and stops the flow to prevent damage.

### The Default Thresholds

| Threshold | Default | Meaning |
|-----------|---------|---------|
| Daily loss limit | 2.0% | Stop trading if today's P&L is ≤ -2% |
| Weekly loss limit | 5.0% | Stop trading if this week's P&L is ≤ -5% |
| Monthly loss limit | 8.0% | Stop trading if this month's P&L is ≤ -8% |
| Consecutive loss cooldown | 2 losses | 2+ consecutive losses triggers a cooldown |
| Cooldown duration | 24 hours | Cooldown lasts 24h from the most recent loss |

### How It Works

1. **Fetch recent trades** — reads the last 40 days of closed trades from the journal
2. **Calculate period P&L** — sums up realized P&L for today, this week, and this month
3. **Check loss limits** — if any period P&L breaches its limit, state is "halted"
4. **Check losing streak** — counts consecutive losses; if ≥ 2 and within cooldown window, state is "cooldown"
5. **Return verdict** — "trading_allowed", "cooldown", or "halted"

**Priority:** Loss limits take priority over cooldowns. If you've hit a loss limit, you're halted — period. The cooldown only applies if you haven't hit a loss limit but have had too many consecutive losses.

### The Math

**Period P&L:** For each period (daily, weekly, monthly), sums `realized_pnl_pct * 100` over closed trades where `closed_at >= period_start`. This assumes roughly equal-sized positions — it's a behavioral guardrail, not accounting-grade P&L.

**Consecutive-loss streak:** Sorts closed trades by `closed_at`, walks through them incrementing a counter for each loss (`pnl <= 0`) and resetting to 0 on any win (`pnl > 0`). Returns the current streak and the timestamp of the most recent loss.

**Cooldown trigger:** Fires when `streak >= consecutive_loss_cooldown` AND `last_loss_at + cooldown_hours` is still in the future. An old losing streak with no recent trades doesn't perpetually block new entries.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `config` | `CircuitBreakerConfig \| None` | `None` | Optional custom thresholds (uses defaults if omitted) |

### Returns

A dictionary with:
```json
{
  "state": "cooldown",
  "triggered_rules": [
    "2 consecutive losses — cooldown for 24h after the last loss"
  ],
  "cooldown_until": "2026-08-16T09:15:00+00:00",
  "period_pnl": {
    "daily_pct": -1.2,
    "weekly_pct": -3.4,
    "monthly_pct": -3.4
  }
}
```

**State values:**
- `trading_allowed` — you're clear to trade
- `cooldown` — you've had too many consecutive losses, wait until `cooldown_until`
- `halted` — you've hit a loss limit, stop trading for the period

### Usage

**Python API:**
```python
result = await check_circuit_breaker()
if result["state"] == "halted":
    print(f"Halted: {result['triggered_rules']}")
```

**Agent tool:**
```
check_risk_circuit_breaker()
```

---

## check_discipline_gate

**Agent tool:** `check_trade_discipline`

The pre-trade checklist — validates a specific trade idea against the rules a disciplined trader should never skip.

### What It Does

Before you advance a trade to `entry_ready` or `active`, this gate checks:
1. Do you have a written thesis?
2. Do you have an entry plan?
3. Do you have a stop-loss defined?
4. Is the circuit breaker allowing trades?
5. Is the market regime not bearish?

If any of these fail, the trade is blocked. This forces you to have a plan before you act, which is the foundation of disciplined trading.

### The Five Checks

| Check | Passes if | Why it matters |
|-------|-----------|----------------|
| `written_thesis` | Thesis is non-empty | You need to know *why* you're trading |
| `entry_plan` | Entry plan is non-empty | You need to know *when* and *how* to enter |
| `stop_defined` | Stop price is set | You need to know *when* to exit if you're wrong |
| `circuit_breaker` | State is "trading_allowed" | Don't trade if you're on a losing streak |
| `market_regime` | Regime is not "bear" or "strong-bear" | Don't fight the market |

### How It Works

1. **Load the trade** — fetches the trade idea from the journal (read-only, no status change)
2. **Check thesis and plan** — verifies they're non-empty strings
3. **Check stop** — verifies a stop price is defined
4. **Check circuit breaker** — calls `check_circuit_breaker()` and verifies state is "trading_allowed"
5. **Check market regime** — calls `detect_market_regime()` and verifies regime is not bearish
6. **Return verdict** — "pass" if all checks pass, "blocked" otherwise

**Composition, not duplication:** The discipline gate doesn't re-implement the circuit breaker or regime detection logic — it calls those tools and aggregates their results. This keeps the code clean and ensures consistency.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `trade_id` | `str` | required | Trade idea ID to check |
| `config` | `CircuitBreakerConfig \| None` | `None` | Optional custom circuit breaker thresholds |

### Returns

A dictionary with:
```json
{
  "result": "blocked",
  "trade_id": "a1b2c3d4e5f6",
  "checks": {
    "written_thesis": {"passed": true, "detail": "Breaking out of a 6-week base..."},
    "entry_plan": {"passed": true, "detail": "Buy on close above 135..."},
    "stop_defined": {"passed": false, "detail": "no stop"},
    "circuit_breaker": {"passed": true, "detail": "state=trading_allowed"},
    "market_regime": {"passed": true, "detail": "regime=neutral (exposure 40-70%)"}
  }
}
```

**Result values:**
- `pass` — all checks passed, you can proceed
- `blocked` — one or more checks failed, see which ones in `checks`

### Usage

**Python API:**
```python
gate = await check_discipline_gate(provider, trade_id="a1b2c3d4e5f6")
if gate["result"] == "blocked":
    failed = [name for name, check in gate["checks"].items() if not check["passed"]]
    print(f"Blocked: {', '.join(failed)}")
```

**Agent tool:**
```
check_trade_discipline(trade_id="a1b2c3d4e5f6")
```

---

## CircuitBreakerConfig

**Agent tool:** Not exposed (configuration object)

Defines the loss-limit and losing-streak thresholds for the circuit breaker.

### What It Does

Lets you customize the circuit breaker thresholds. The defaults are conservative (2% daily, 5% weekly, 8% monthly), but you can adjust them based on your risk tolerance and trading style.

### Configuration Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `daily_loss_limit_pct` | `float` | `2.0` | Trip if today's P&L ≤ -X% |
| `weekly_loss_limit_pct` | `float` | `5.0` | Trip if this week's P&L ≤ -X% |
| `monthly_loss_limit_pct` | `float` | `8.0` | Trip if this month's P&L ≤ -X% |
| `consecutive_loss_cooldown` | `int` | `2` | X+ consecutive losses triggers cooldown |
| `cooldown_hours` | `int` | `24` | Cooldown lasts X hours from last loss |

### Usage

```python
from quantagent.tools.risk_gate import CircuitBreakerConfig

# Use custom thresholds
config = CircuitBreakerConfig(
    daily_loss_limit_pct=1.5,
    consecutive_loss_cooldown=3,
    cooldown_hours=48
)

result = await check_circuit_breaker(config=config)
```

---

## Summary

These risk gate tools help you maintain trading discipline:

- **check_circuit_breaker** — should you be trading right now? (checks loss limits and losing streaks)
- **check_discipline_gate** — is this specific trade idea ready to execute? (checks thesis, plan, stop, circuit breaker, and market regime)
- **CircuitBreakerConfig** — customize the circuit breaker thresholds

Use these tools to:
- Prevent revenge-trading after a bad day or week
- Force yourself to have a plan before entering trades
- Avoid fighting a bearish market regime
- Enforce cooling-off periods after consecutive losses

Remember: the best traders are not the ones who never lose — they're the ones who manage their risk and avoid catastrophic drawdowns. These tools help you do that by enforcing discipline when your emotions might be telling you to do something stupid.

The circuit breaker is especially important for agent-driven trading, where there's no human to say "maybe I should take a break." The agent will respect the circuit breaker and stop looking for new trades until the cooldown expires or the next period begins.

# Trade Journal Tools

`quantagent/tools/trade_journal.py`

A trade journal that forces discipline into your trading process. Every trade idea is written down with a thesis *before* it's acted on, status can only move forward (no quietly erasing a bad call), and every close is scored against what the market actually did intraday (MAE/MFE), not just the entry-to-exit return.

The journal is stored in a single SQLite file at `~/.quantagent/trades.db`.

---

## The Trade Lifecycle

Every trade in the journal follows a **forward-only lifecycle** — you can't move backwards or skip stages. This enforces discipline: you can't "un-close" a trade or pretend you had a different plan after the fact.

```
idea → entry_ready → active → partially_closed → closed
  ↓         ↓
invalidated invalidated
```

**Lifecycle stages:**
- **idea** — you've written down the thesis and plan, but haven't acted yet
- **entry_ready** — the setup is forming, you're watching for entry
- **active** — you've entered the trade and it's live
- **partially_closed** — you've taken partial profits (optional stage)
- **closed** — the trade is complete, P&L is recorded
- **invalidated** — the thesis was wrong, you killed the trade before entry

**Terminal states:** `closed` and `invalidated` are final — no transitions out.

**Rejected transitions:** You can't go from `active` back to `idea`, or from `closed` to `active`, or skip `entry_ready` and go straight from `idea` to `active`. The journal enforces the lifecycle.

---

## log_trade_idea

**Agent tool:** `journal_log_trade`

Records a new trade idea before any money moves — the "write it down before you act" step.

### What It Does

Creates a new trade idea in the journal with:
- **Symbol** — what stock you're looking at
- **Thesis** — *why* you think this trade will work
- **Entry plan** — *when* and *how* you'll enter (price level, conditions, etc.)
- **Target** (optional) — where you expect the stock to go
- **Stop** (optional) — where you'll exit if you're wrong

This forces you to articulate your thinking *before* you act, so later you can review whether your thesis was right or whether you were just guessing.

### How It Works

1. **Validate inputs** — thesis and entry plan are required (can't be empty)
2. **Generate ID** — creates a short 12-character hex UUID
3. **Set timestamps** — `created_at` is set to now (UTC)
4. **Store in database** — saves the trade idea with status "idea"
5. **Return trade** — returns the complete `TradeIdea` object

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `symbol` | `str` | required | Stock ticker (upper-cased internally) |
| `thesis` | `str` | required | Why this trade should work |
| `entry_plan` | `str` | required | When and how you'll enter |
| `target` | `float \| None` | `None` | Price target |
| `stop` | `float \| None` | `None` | Stop-loss price |

### Returns

A `TradeIdea` object with status "idea" and all fields populated.

### Usage

**Python API:**
```python
trade = await log_trade_idea(
    symbol="NVDA",
    thesis="Breaking out of a 6-week base on rising volume; AI capex cycle intact.",
    entry_plan="Buy on close above 135 with 2% account risk.",
    target=160.0,
    stop=128.0
)
# trade.id == "a1b2c3d4e5f6", trade.status == "idea"
```

**Agent tool:**
```
journal_log_trade(
    symbol="NVDA",
    thesis="Breaking out of a 6-week base on rising volume",
    entry_plan="Buy on close above 135",
    target=160.0,
    stop=128.0
)
```

---

## update_trade_status

**Agent tool:** `journal_update_status`

Advances a trade to its next lifecycle stage — how a plan becomes a live position.

### What It Does

Moves a trade from one stage to the next (e.g. `idea` → `entry_ready`, `entry_ready` → `active`). You can also append a note to document what happened.

### How It Works

1. **Validate transition** — checks that the move is allowed by the lifecycle
2. **Check entry price** — if moving to `active`, `entry_price` is required (MAE/MFE math depends on it)
3. **Set timestamps** — `entered_at` is set when moving to `active`, `closed_at` when moving to `closed`
4. **Append note** — if provided, the note is added to the trade's note history (notes are append-only, never overwritten)
5. **Update database** — saves the new status and timestamps
6. **Return trade** — returns the updated `TradeIdea`

**Why entry_price is required for active:** MAE/MFE and P&L calculations at close depend on having a real fill price. The journal refuses to move to `active` without one.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `trade_id` | `str` | required | Trade ID |
| `status` | `str` | required | New status (must be a valid transition) |
| `notes` | `str \| None` | `None` | Optional note to append |
| `entry_price` | `float \| None` | `None` | Required when moving to `active` |

### Returns

The updated `TradeIdea` object.

### Usage

**Python API:**
```python
trade = await update_trade_status(
    trade_id="a1b2c3d4e5f6",
    status="active",
    entry_price=136.20,
    notes="Filled at open, slightly above plan."
)
```

**Agent tool:**
```
journal_update_status(
    trade_id="a1b2c3d4e5f6",
    status="active",
    entry_price=136.20,
    notes="Filled at open"
)
```

---

## close_trade

**Agent tool:** `journal_close_trade`

Closes an active trade, recording the realized P&L and scoring the trade against the best/worst prices the market offered during the holding period (MAE/MFE).

### What It Does

Marks a trade as closed and calculates:
- **Realized P&L** — the actual return from entry to exit
- **MAE (Maximum Adverse Excursion)** — the worst unrealized drawdown the position saw
- **MFE (Maximum Favorable Excursion)** — the best unrealized gain the position saw
- **Outcome** — "win" if P&L > 0, "loss" otherwise

This is the "how did this trade actually behave" postmortem step. MAE/MFE tell you whether you managed the trade well — if your MFE was 20% but you only captured 5%, you left a lot on the table.

### How It Works

1. **Validate transition** — only `active` or `partially_closed` trades can close
2. **Calculate P&L** — `(exit_price / entry_price) - 1`
3. **Determine outcome** — "win" if P&L > 0, "loss" otherwise
4. **Fetch price history** — downloads 1 year of daily OHLCV for the symbol
5. **Calculate MAE/MFE:**
   - Window the data to bars on/after `entered_at`
   - **MFE** = `(max(High) / entry_price) - 1` — best unrealized gain
   - **MAE** = `(min(Low) / entry_price) - 1` — worst unrealized drawdown
6. **Store results** — saves exit price, P&L, MAE, MFE, outcome, and closed_at timestamp
7. **Return trade** — returns the completed `TradeIdea`

**MAE/MFE are long-side only:** This implementation assumes long positions. For short positions, the formulas would be inverted.

**Graceful failure:** If the price data fetch fails, MAE/MFE are set to `None` and a warning is logged, but the trade still closes. A data outage shouldn't block you from recording P&L.

### Parameters

| Name | Type | Description |
|------|------|-------------|
| `provider` | `AbstractDataProvider` | Your data provider |
| `trade_id` | `str` | Trade ID |
| `exit_price` | `float` | Exit price |
| `outcome_notes` | `str \| None` | Optional notes about the exit |

### Returns

The updated `TradeIdea` with status "closed" and all outcome fields populated.

### Usage

**Python API:**
```python
trade = await close_trade(
    provider,
    trade_id="a1b2c3d4e5f6",
    exit_price=152.00,
    outcome_notes="Hit target, momentum stalling on lower volume."
)
# trade.realized_pnl_pct == 0.1160 (11.6% gain)
# trade.outcome == "win"
# trade.mfe_pct == 0.1523 (15.23% was the best unrealized gain)
# trade.mae_pct == -0.0234 (-2.34% was the worst unrealized drawdown)
```

**Agent tool:**
```
journal_close_trade(
    trade_id="a1b2c3d4e5f6",
    exit_price=152.00,
    outcome_notes="Hit target"
)
```

---

## get_open_trades

**Agent tool:** `journal_open_trades`

Lists everything still "live" in the journal — ideas not yet acted on, entries pending, active positions, and partial exits.

### What It Does

Returns all trades that haven't reached a terminal state (`closed` or `invalidated`). This gives you a single view of your open risk.

### How It Works

Filters on the fixed `OPEN_STATUSES` tuple: `idea`, `entry_ready`, `active`, `partially_closed`. Returns trades ordered most-recent-first.

### Parameters

None.

### Returns

A list of `TradeIdea` objects, most recent first.

### Usage

**Python API:**
```python
open_trades = await get_open_trades()
for trade in open_trades:
    print(f"{trade.symbol}: {trade.status} - {trade.thesis[:50]}...")
```

**Agent tool:**
```
journal_open_trades()
```

---

## get_trade_history

**Agent tool:** `journal_history`

Retrieves trades created within a lookback window, optionally filtered by status.

### What It Does

Returns trades created in the last N days, optionally filtered to a specific status (e.g. only "closed" trades for P&L review).

### How It Works

Filters on `created_at` (not `closed_at`), so a trade logged 29 days ago that's still open shows up in a 30-day history even if it hasn't closed. This gives you a complete picture of recent activity.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `days` | `int` | `30` | Lookback window in days |
| `status` | `str \| None` | `None` | Optional status filter |

### Returns

A list of `TradeIdea` objects, most recent first.

### Usage

**Python API:**
```python
closed_last_week = await get_trade_history(days=7, status="closed")
```

**Agent tool:**
```
journal_history(days=7, status="closed")
```

---

## compute_trade_stats

**Agent tool:** `journal_stats`

Summarizes your trading performance across all closed trades — the numbers that tell you whether your process actually has an edge.

### What It Does

Calculates key performance metrics:
- **Win rate** — what percentage of trades were winners?
- **Average win/loss** — how much do you make when you're right vs. lose when you're wrong?
- **Profit factor** — gross profits / gross losses (should be > 1.0)
- **Expectancy** — average return per trade
- **Max consecutive losses** — your worst losing streak
- **Average MAE/MFE** — how much drawdown did you typically endure, and how much unrealized gain did you leave on the table?

### The Math

**Win rate:** `wins / total_trades` where wins are trades with `pnl > 0`.

**Average win:** `sum(wins) / len(wins)` — the mean P&L of winning trades.

**Average loss:** `sum(losses) / len(losses)` — the mean P&L of losing trades (a negative number).

**Profit factor:** `sum(wins) / abs(sum(losses))` — gross profit divided by gross loss. A profit factor of 2.0 means you made $2 for every $1 you lost. If there are no losses, profit factor is `None` (not infinite).

**Expectancy:** `sum(all_pnls) / len(all_pnls)` — the mean realized return per trade. This is equivalent to `(win_rate * avg_win) + (loss_rate * avg_loss)`.

**Max consecutive losses:** Walks through trades in chronological order, counting consecutive losses (`pnl <= 0`) and resetting on any win (`pnl > 0`). Returns the longest streak.

**Average MAE/MFE:** Mean of the non-null `mae_pct` and `mfe_pct` values across all closed trades.

### Parameters

None.

### Returns

A dictionary with:
```json
{
  "total_trades": 12,
  "win_rate": 0.5833,
  "avg_win": 0.084,
  "avg_loss": -0.031,
  "profit_factor": 2.71,
  "expectancy": 0.0264,
  "max_consecutive_losses": 2,
  "avg_mae": -0.045,
  "avg_mfe": 0.112
}
```

Or just `{"total_trades": 0}` if there are no closed trades with recorded P&L.

### Usage

**Python API:**
```python
stats = await compute_trade_stats()
print(f"Win rate: {stats['win_rate']:.1%}")
print(f"Profit factor: {stats['profit_factor']:.2f}")
print(f"Expectancy: {stats['expectancy']:.2%} per trade")
```

**Agent tool:**
```
journal_stats()
```

---

## TradeIdea Model

**Agent tool:** Not exposed (return type)

The data model representing a single trade idea and its lifecycle state.

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | 12-character hex UUID |
| `symbol` | `str` | Stock ticker |
| `thesis` | `str` | Why this trade should work |
| `entry_plan` | `str` | When and how to enter |
| `target` | `float \| None` | Price target |
| `stop` | `float \| None` | Stop-loss price |
| `status` | `str` | Current lifecycle stage |
| `created_at` | `datetime` | When the idea was logged |
| `entered_at` | `datetime \| None` | When the trade was entered |
| `closed_at` | `datetime \| None` | When the trade was closed |
| `entry_price` | `float \| None` | Fill price |
| `exit_price` | `float \| None` | Exit price |
| `realized_pnl_pct` | `float \| None` | Realized P&L as a decimal |
| `mae_pct` | `float \| None` | Maximum adverse excursion |
| `mfe_pct` | `float \| None` | Maximum favorable excursion |
| `outcome` | `str \| None` | "win" or "loss" |
| `notes` | `list[str]` | Append-only note history |

---

## Summary

These trade journal tools help you maintain a disciplined trading process:

- **log_trade_idea** — write down your thesis and plan before acting
- **update_trade_status** — advance trades through the lifecycle
- **close_trade** — record the outcome and calculate MAE/MFE
- **get_open_trades** — see what's still live
- **get_trade_history** — review recent activity
- **compute_trade_stats** — measure your performance

Use these tools to:
- Force yourself to articulate your thinking before trading
- Track every trade from idea to close
- Score your trades against what the market actually did (MAE/MFE)
- Measure your edge with win rate, profit factor, and expectancy
- Review your process and identify areas for improvement

Remember: the journal isn't just bookkeeping — it's a tool for learning. By reviewing your closed trades and their MAE/MFE, you can see whether you're managing entries and exits well, whether you're letting winners run, and whether you're cutting losers quickly. Over time, this feedback loop helps you refine your process and improve your results.

The forward-only lifecycle is intentional — it prevents you from rewriting history. Once a trade is closed, the numbers are locked in. You can't go back and change your thesis or pretend you had a different plan. This honesty is what makes the journal useful for learning.

# Trade Journal

Source: `quantagent/tools/trade_journal.py`

A trade journal with a **forward-only lifecycle** and automatic **MAE/MFE**
(Maximum Adverse/Favorable Excursion) capture at close. Storage is a single
SQLite file at `~/.quantagent/trades.db` (schema created on first connect via
`_SCHEMA` / `CREATE TABLE IF NOT EXISTS trades`).

The point of this module isn't bookkeeping for its own sake — it's forcing
the discipline that separates a repeatable trading process from noise: every
idea is written down with a thesis *before* it's acted on, status can only
move forward (no quietly erasing a bad call), and every close is scored
against what the market actually did intraday (MAE/MFE), not just the
entry-to-exit return.

---

## TradeIdea (model)

**Agent-facing tool name:** Not exposed as an agent tool (it's the return
type of every journal function below).

**Purpose:** The single record representing one trade idea and its current
lifecycle state — thesis, entry plan, target/stop, timestamps, prices, and
computed outcome fields.

**Why built this way:** A pydantic `BaseModel` gives every journal function a
validated, serializable return type (`model_dump_json`) so the agent layer
can hand it straight back to the LLM or the TUI without extra glue. Fields
that only make sense once a trade has happened (`entered_at`, `exit_price`,
`mae_pct`, `mfe_pct`, `outcome`) are `None` until they're populated by
`update_trade_status`/`close_trade`, rather than being computed at read time —
so closed-trade numbers are immutable facts, not re-derived on every read.

**Math:** N/A (no computation lives on the model itself).

**Usage:** Fields: `id` (12-hex-char uuid), `symbol`, `thesis`, `entry_plan`,
`target`, `stop`, `status`, `created_at`, `entered_at`, `closed_at`,
`entry_price`, `exit_price`, `realized_pnl_pct`, `mae_pct`, `mfe_pct`,
`outcome` (`"win"` / `"loss"`), `notes` (list of strings, append-only).

---

## Lifecycle state machine

Enforced by `_require_transition`, backed by the `_TRANSITIONS` table. This
is the one piece of logic every other function in the module depends on —
**no transition may move a trade backwards**, and any transition not
explicitly listed raises `ValueError`:

```
idea            -> {entry_ready, invalidated}
entry_ready     -> {active, invalidated}
active          -> {partially_closed, closed}
partially_closed -> {closed}
closed          -> {}   (terminal)
invalidated     -> {}   (terminal)
```

```
        ┌──────┐   entry_ready    ┌─────────────┐    active    ┌────────┐
        │ idea │ ───────────────> │ entry_ready │ ────────────>│ active │
        └──┬───┘                 └──────┬──────┘               └───┬────┘
           │ invalidated                │ invalidated              │
           v                            v                          │ partially_closed / closed
     ┌─────────────┐              ┌─────────────┐                  v
     │ invalidated │              │ invalidated │           ┌─────────────────┐   closed   ┌────────┐
     └─────────────┘              └─────────────┘           │ partially_closed│ ──────────>│ closed │
                                                              └─────────────────┘            └────────┘
                (active can also go straight to closed)
```

Rejected examples: `active -> idea`, `closed -> active`, `invalidated ->`
anything, `idea -> active` (must pass through `entry_ready` first), `idea ->
closed`. The error message echoes the allowed set, e.g. *"Invalid transition
closed -> active (lifecycle is forward-only; allowed from closed: none)"*.

---

## log_trade_idea

**Agent-facing tool name:** `journal_log_trade`

**Purpose:** Records a new trade idea before any money moves — symbol,
thesis, entry plan, optional target/stop — starting it in `idea` status.
This is the "write it down before you act" step that everything downstream
(discipline gate, stats) depends on existing.

**Why built this way:** Forces a thesis and entry plan to exist as plain
text at creation time, so later postmortems can be checked against what was
actually planned rather than a reconstructed memory. The symbol is
uppercased for consistent lookups; the id is a short (12 hex char)
`uuid4` slice — long enough to avoid collisions, short enough to reference
in conversation.

**Math:** None.

**Usage:**
- Params: `symbol: str`, `thesis: str`, `entry_plan: str`, `target: float |
  None = None`, `stop: float | None = None`.
- Returns: `TradeIdea` (status `"idea"`, `created_at` set to now UTC).
- Example:
  ```python
  trade = await log_trade_idea(
      symbol="nvda",
      thesis="Breaking out of a 6-week base on rising volume; AI capex cycle intact.",
      entry_plan="Buy on close above 135 with 2% account risk.",
      target=160.0,
      stop=128.0,
  )
  # trade.id == "a1b2c3d4e5f6", trade.status == "idea"
  ```

---

## update_trade_status

**Agent-facing tool name:** `journal_update_status`

**Purpose:** Advances a journaled trade to its next lifecycle stage (e.g.
`idea -> entry_ready`, `entry_ready -> active`), optionally appending a note.
This is how a plan becomes a live position in the record.

**Why built this way:** Every call runs through `_require_transition` first,
so a stale or careless status update can't silently rewrite history (you
can't "un-close" a trade or skip backwards to relitigate a decision).
Moving to `active` specifically requires `entry_price` — MAE/MFE and P&L math
at close depend on having a real fill price, so the function refuses to
enter that state without one. `entered_at`/`closed_at` are stamped
automatically based on the target status, and notes are appended (never
overwritten) to `notes`, preserving a running commentary log per trade.

**Math:** None directly; it sets up the inputs (`entry_price`, `entered_at`)
that `close_trade` later uses for P&L/MAE/MFE.

**Usage:**
- Params: `trade_id: str`, `status: str`, `notes: str | None = None`,
  `entry_price: float | None = None`.
- Raises `ValueError` on an illegal transition, or on moving to `active`
  without `entry_price`.
- Returns: updated `TradeIdea`.
- Example:
  ```python
  trade = await update_trade_status(
      trade_id="a1b2c3d4e5f6",
      status="active",
      entry_price=136.20,
      notes="Filled at open, slightly above plan.",
  )
  ```
- Legal transitions: see the [lifecycle diagram](#lifecycle-state-machine)
  above.

---

## close_trade

**Agent-facing tool name:** `journal_close_trade` (provider-bound wrapper
`_journal_close_trade` in `tools_registry.py`, registered via
`_bind_provider`)

**Purpose:** Closes an active (or partially closed) trade, recording the
realized P&L and scoring the trade against the best/worst prices the market
offered during the holding period (MAE/MFE) — the core "how did this trade
actually behave" postmortem step.

**Why built this way:** `_require_transition(trade.status, "closed")` is
still enforced here — only `active` or `partially_closed` trades can close,
so you can't close an `idea` that was never entered. Outcome is a simple
binary `"win"`/`"loss"` classification (`pnl > 0` is a win, everything else
— including flat — counts as a loss) so `compute_trade_stats` has an
unambiguous win/loss split downstream. MAE/MFE computation failures (data
provider errors) are swallowed and logged rather than raised, so a data
outage doesn't block the ability to close a position and record P&L.

**Math:**
- Realized P&L: `pnl = round(exit_price / entry_price - 1, 4)` (i.e. simple
  percentage return; `None` if `entry_price` is unset).
- Outcome: `"win"` if `pnl is not None and pnl > 0`, else `"loss"`.
- MAE/MFE (`_compute_excursions`, long-side only):
  1. Requires both `entry_price` and `entered_at`; otherwise returns
     `(None, None)`.
  2. Fetches 1 year of daily OHLCV for the symbol via
     `provider.get_ohlcv(symbol, period="1y")`.
  3. Windows the OHLCV to bars on/after `entered_at` normalized to midnight
     (`pd.Timestamp(entered_at).normalize()`), inclusive.
  4. **MFE** (Maximum Favorable Excursion) = `round(window["High"].max() /
     entry_price - 1, 4)` — the best unrealized gain the position saw.
  5. **MAE** (Maximum Adverse Excursion) = `round(window["Low"].min() /
     entry_price - 1, 4)` — the worst unrealized drawdown the position saw
     (a negative number for a normal long trade that dipped below entry).
  6. If the OHLCV fetch throws, or the windowed frame is empty, both are
     `None` (logged as a warning, not raised).

**Usage:**
- Params: `provider: AbstractDataProvider`, `trade_id: str`, `exit_price:
  float`, `outcome_notes: str | None = None`.
- Raises `ValueError` if the trade isn't in `active`/`partially_closed`.
- Returns: updated `TradeIdea` with `status="closed"`, `closed_at`,
  `exit_price`, `realized_pnl_pct`, `mae_pct`, `mfe_pct`, `outcome` all set.
- Example:
  ```python
  trade = await close_trade(
      provider, trade_id="a1b2c3d4e5f6", exit_price=152.00,
      outcome_notes="Hit target, momentum stalling on lower volume.",
  )
  # trade.realized_pnl_pct == round(152.00/136.20 - 1, 4) == 0.1160
  # trade.outcome == "win"
  ```

---

## get_open_trades

**Agent-facing tool name:** `journal_open_trades`

**Purpose:** Lists everything still "live" in the journal — ideas not yet
acted on, entries pending, active positions, and partial exits — so the
agent (or trader) always has a single view of open risk.

**Why built this way:** Filters on the fixed `OPEN_STATUSES` tuple
(`idea, entry_ready, active, partially_closed`), i.e. anything not
`closed`/`invalidated`, ordered most-recent-first — a cheap, always-correct
definition of "still open" that stays consistent as new statuses can't be
added without touching the lifecycle table itself.

**Math:** None.

**Usage:**
- Params: none.
- Returns: `list[TradeIdea]`.
- Example: `open_trades = await get_open_trades()`

---

## get_trade_history

**Agent-facing tool name:** `journal_history`

**Purpose:** Retrieves journaled trades created within a lookback window,
optionally filtered to one lifecycle status — used for reviewing recent
activity and as the data source `check_circuit_breaker` reads from.

**Why built this way:** Filters on `created_at` (not `closed_at`), so a
trade logged 29 days ago that's still open shows up in a 30-day history even
if it hasn't closed. The optional `status` filter lets callers narrow to,
say, just `"closed"` trades for P&L review without a separate query.

**Math:** None.

**Usage:**
- Params: `days: int = 30`, `status: str | None = None`.
- Returns: `list[TradeIdea]`, most-recent-first.
- Example:
  ```python
  closed_last_week = await get_trade_history(days=7, status="closed")
  ```

---

## compute_trade_stats

**Agent-facing tool name:** `journal_stats`

**Purpose:** Summarizes edge and risk-management quality across every closed
trade with a recorded P&L — win rate, profit factor, expectancy, and the
worst losing streak — the numbers that tell you whether your process
actually has an edge.

**Why built this way:** Only trades with `status = 'closed' AND
realized_pnl_pct IS NOT NULL` are included, so open positions or trades
closed without a fill price can't distort the stats. An empty journal
returns `{"total_trades": 0}` rather than raising or dividing by zero.
`profit_factor` is explicitly `None` (not `0` or `inf`) when there are no
losses, since "infinite profit factor" isn't a meaningful number to feed
back into risk sizing.

**Math** (all computed over the list of `realized_pnl_pct` values, each a
fractional return like `0.116` for +11.6%):
- `wins` = pnls where `p > 0`; `losses` = pnls where `p <= 0` (flat trades
  count as losses, matching `close_trade`'s outcome classification).
- **Win rate** = `len(wins) / len(pnls)`.
- **Average win** = `sum(wins) / len(wins)` (0.0 if no wins).
- **Average loss** = `sum(losses) / len(losses)` (0.0 if no losses; this is
  a negative number when there are losses).
- **Gross loss** = `abs(sum(losses))`.
- **Profit factor** = `sum(wins) / gross_loss` — gross profit divided by
  gross loss; `None` if `gross_loss == 0`.
- **Expectancy** = `sum(pnls) / len(pnls)` — i.e. the mean realized return
  per trade across the whole sample (equivalent to `win_rate * avg_win +
  loss_rate * avg_loss` since it's the same set partitioned into wins/losses).
- **Max consecutive losses** (`_max_consecutive_losses`): walks the P&L list
  in chronological order (`ORDER BY closed_at`), incrementing a running
  streak counter for each `pnl <= 0` and resetting to 0 on any `pnl > 0`;
  returns the largest streak seen.
- `avg_mae` / `avg_mfe`: plain means of the non-null `mae_pct`/`mfe_pct`
  values across the same closed trades (`None` if none recorded).
- All numeric outputs are `round(x, 4)`.

**Usage:**
- Params: none.
- Returns: `dict` — `{total_trades, win_rate, avg_win, avg_loss,
  profit_factor, expectancy, max_consecutive_losses, avg_mae, avg_mfe}`
  (or just `{"total_trades": 0}` when the journal has no qualifying
  closed trades).
- Example:
  ```python
  stats = await compute_trade_stats()
  # {"total_trades": 12, "win_rate": 0.5833, "avg_win": 0.084,
  #  "avg_loss": -0.031, "profit_factor": 2.71, "expectancy": 0.0264,
  #  "max_consecutive_losses": 2, "avg_mae": -0.045, "avg_mfe": 0.112}
  ```

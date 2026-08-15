# Screener Tools

Source: `quantagent/tools/screener.py`

Fundamental screening fetches quotes/fundamentals per symbol with bounded concurrency
(semaphore of 8 concurrent requests). Technical and pattern screens batch-download 1
year of daily OHLCV for the whole universe up front and then evaluate every rule
locally against the in-memory frames — no per-symbol network round trips once the
batch download completes.

Note: a Piotroski F-Score screen is intentionally not offered here — the current data
providers don't supply the balance-sheet fields the F-Score needs, so it would
silently score 0. It can return once a richer fundamentals provider (e.g. FMP) is
wired in.

---

## screen_stocks

**Agent-facing tool name:** `screen_stocks_tool`

**Purpose:** Filters a universe of stocks (e.g. the S&P 500) down to those meeting
a set of fundamental thresholds — valuation, profitability, leverage, growth,
dividend yield, market cap, volume, and beta — and returns them sorted and ranked.
This is the classic "find me cheap, profitable, growing companies" screen.

**Why built this way:**
- The universe is resolved via `load_universe`, so the search space is bounded by
  whichever named universe is passed in (`sp500`, `nasdaq100`, `dow30`,
  `sector_etfs`, or a custom universe) — there is no hardcoded symbol cap; an
  optional `max_symbols` lets a caller truncate the universe for a faster/cheaper
  run, but the default is "the whole universe."
- Per-symbol fundamentals + quote calls are fetched concurrently with a semaphore
  capped at 8 in-flight requests, trading off provider rate limits against
  throughput. Progress is reported every 25 completed symbols
  (`_PROGRESS_EVERY = 25`).
- A symbol that fails to fetch (`get_fundamentals`/`get_quote` raises) is silently
  dropped from the result set rather than aborting the whole screen — screens are
  best-effort over hundreds of symbols and a handful of provider hiccups shouldn't
  fail the entire call. Failures are logged at `debug` level per-symbol and at
  `warning` level if the universe itself fails to resolve.
- Filtering criteria are looked up from a small operator dispatch table
  (`_CRITERIA_DISPATCH`) mapping criterion keys to `(column, operator)` pairs, so
  adding a new fundamental filter is a one-line table entry. Unknown criteria keys
  are logged and ignored (the DataFrame passes through unfiltered for that key)
  rather than raising, so a screen degrades gracefully instead of erroring out on a
  typo.

**Math:** No composite scoring — this is pure boolean filtering, one comparison per
criterion, all criteria AND-ed together (a row must pass every supplied criterion to
survive). Supported keys and their comparisons:

| Criteria key | Column | Comparison |
|---|---|---|
| `pe_lt` / `pe_gt` | `pe_ratio` | `<` / `>` |
| `pb_lt` / `pb_gt` | `pb_ratio` | `<` / `>` |
| `roe_gt` | `roe` | `>` |
| `roa_gt` | `roa` | `>` |
| `debt_equity_lt` | `debt_equity` | `<` |
| `mcap_gt` / `mcap_lt` (aliases `market_cap_gt` / `market_cap_lt`) | `market_cap` | `>` / `<` |
| `volume_gt` | `volume` | `>` |
| `dividend_yield_gt` | `dividend_yield` | `>` |
| `revenue_growth_gt` | `revenue_growth` | `>` |
| `eps_growth_gt` | `eps_growth` | `>` |
| `beta_lt` | `beta` | `<` |

After filtering, the result is sorted by `sort_by` (default `market_cap`, descending
by default since `ascending=False`) and truncated to `limit` rows (default 20). No
built-in thresholds are hardcoded — the caller supplies the actual numeric cutoffs.

**Usage:**
- `provider: AbstractDataProvider` — market data provider.
- `universe: str = "sp500"` — universe name to screen.
- `criteria: dict | None = None` — filter dict using the keys above, e.g.
  `{"pe_lt": 15, "roe_gt": 0.20}`.
- `sort_by: str = "market_cap"` — column to sort by.
- `ascending: bool = False` — sort direction.
- `limit: int = 20` — max rows returned.
- `max_symbols: int | None = None` — optional cap on symbols fetched (default: whole
  universe).
- Returns: `pd.DataFrame` with columns `symbol, name, pe_ratio, pb_ratio, roe, roa,
  debt_equity, market_cap, volume, dividend_yield, revenue_growth, eps_growth, beta,
  price` (empty DataFrame if the universe or all fetches fail).

Agent-facing wrapper (`screen_stocks_tool`) accepts `criteria` as a JSON string
(e.g. `'{"pe_lt": 15, "roe_gt": 0.20}'`), restricts the documented universe choices
to `sp500`/`nasdaq100` in its docstring (though any resolvable universe works), runs
under a 120s timeout, and returns `"No stocks matched the criteria."` when empty
instead of an empty JSON array.

```python
df = await screen_stocks(
    provider, universe="sp500",
    criteria={"pe_lt": 15, "roe_gt": 0.20, "debt_equity_lt": 1.0},
    sort_by="roe", ascending=False, limit=10,
)
```

---

## screen_by_fundamentals

**Agent-facing tool name:** Not exposed as an agent tool.

**Purpose:** A thin convenience alias of `screen_stocks` with a larger default
result set (50 rows instead of 20) — same fundamental filtering, just tuned for
callers that want a broader list back.

**Why built this way:** It exists purely to give code-level callers (not the LLM
agent) a friendlier default `limit` without duplicating any filtering logic — it
delegates entirely to `screen_stocks` and passes through `sort_by`'s implicit
default (`market_cap`) and `ascending`'s implicit default (`False`) unchanged. It is
not imported into `quantagent/agent/tools_registry.py`, so the agent cannot call it
directly; the agent instead uses `screen_stocks_tool` (backed by `screen_stocks`).

**Math:** Identical to `screen_stocks` — see the table there.

**Usage:**
- `provider: AbstractDataProvider`
- `criteria: dict[str, Any]` — required (no default), same keys as `screen_stocks`.
- `universe: str = "sp500"`
- `limit: int = 50`
- Returns: same DataFrame shape as `screen_stocks`.

```python
df = await screen_by_fundamentals(
    provider, criteria={"pe_lt": 20}, universe="nasdaq100", limit=50,
)
```

---

## screen_by_technicals

**Agent-facing tool name:** `screen_technicals_tool`

**Purpose:** Filters a universe down to stocks matching a set of technical
conditions — oversold/overbought RSI, MACD trend direction, price vs. moving
average, volume expansion, Bollinger breakout, and trend strength (ADX) — computed
from one year of daily price history. Useful for momentum/trend-following idea
generation, or as the technical leg of a combined fundamental+technical screen.

**Why built this way:**
- Unlike the fundamental screen (which fetches per-symbol), this batch-downloads
  1-year daily OHLCV for the entire universe in one call
  (`provider.get_batch_ohlcv(tickers, period="1y")`) and then evaluates all
  criteria locally on each symbol's DataFrame — this amortizes network/API cost
  across the whole universe instead of one round trip per indicator per symbol.
- Accepts an optional pre-filtered `symbols` list so it can run against the
  survivors of a prior fundamental screen (this is exactly how `screen_combined`
  chains the two) instead of always re-scanning the full universe.
- Each criterion evaluator returns `None` when there isn't enough history to
  compute it (e.g. fewer than 35 bars for MACD, fewer than 200... actually fewer
  than the required window) rather than `True`/`False` — a row is only kept if
  every requested check evaluates to literal `True`; `None` (insufficient data) is
  treated as a failure to be safe, silently excluding thinly-traded or newly-listed
  symbols rather than guessing.
- An unrecognized criteria key logs a warning and evaluates to `True` (i.e. does
  not filter anything out) — a typo in a criteria key degrades to "no-op" for that
  key rather than crashing the whole screen.

**Math:** Each key maps to one indicator check:

| Criteria key | Value type | Condition |
|---|---|---|
| `rsi_lt` | float | Wilder RSI-14 (`wilder_rsi`, needs ≥15 bars) `<` value |
| `rsi_gt` | float | Wilder RSI-14 `>` value |
| `macd_bullish` | bool | MACD line (EMA12 − EMA26) `>` signal line (9-EMA of MACD line, needs ≥35 bars); result must equal the requested bool |
| `price_above_sma` | int (period) | last close `>` SMA(period) |
| `price_below_sma` | int (period) | last close `<` SMA(period) |
| `volume_expansion` | float (min ratio) | last-day volume ÷ mean(volume, prior 20 days) `>=` value (needs ≥21 bars) |
| `atr_breakout` | bool | last close `>` upper Bollinger band = mean(close, 20) + 2·std(close, 20) (needs ≥20 bars); result must equal the requested bool |
| `adx_gt` | float | ADX-14 (via `compute_indicators(df, ["adx_14"])`, needs ≥30 bars) `>` value |

All requested checks must be `True` (strict AND) for a symbol to be included.
Sorting is not applied within this function — rows are returned in the order the
batch download produced them, truncated to `limit`.

**Usage:**
- `provider: AbstractDataProvider`
- `criteria: dict[str, Any]` — keys per the table above.
- `universe: str = "sp500"` — ignored if `symbols` is given.
- `symbols: list[str] | None = None` — explicit symbol list (e.g. pre-filtered by
  fundamentals).
- `limit: int = 50`
- Returns: `pd.DataFrame` with columns `symbol, price, rsi, volume_ratio` (each
  row's `rsi`/`volume_ratio` reflect the latest values regardless of which criteria
  were requested).

Agent-facing wrapper (`screen_technicals_tool`) takes `criteria` as a required JSON
string (e.g. `'{"rsi_lt": 30, "price_above_sma": 200}'`), documents universes as
`sp500`, `nasdaq100`, `sector_etfs`, or custom, defaults `limit=20`, runs under a
120s timeout, and returns `"No stocks matched the technical criteria."` when empty.

```python
df = await screen_by_technicals(
    provider, criteria={"rsi_lt": 30, "macd_bullish": True}, universe="sp500", limit=20,
)
```

---

## screen_combined

**Agent-facing tool name:** `screen_combined_tool`

**Purpose:** Runs a fundamental screen and a technical screen together and returns
only the stocks that pass both — e.g. "profitable, low-debt companies that are also
currently oversold on RSI." This is the tool to reach for when a trade idea needs
both a quality/valuation filter and a timing/momentum filter.

**Why built this way:** Fundamental filters are cheap (roughly one HTTP round trip
per symbol) and typically narrow the universe a lot, so they run first with a high
internal `limit=10_000` (effectively "no limit" for realistic universe sizes) to
avoid truncating the candidate pool before the technical stage sees it. Only the
fundamental survivors' symbols are then passed into `screen_by_technicals` (which
batch-downloads OHLCV only for those symbols), so the expensive technical
computation is done on the smallest possible symbol set — not the whole universe.
If only one of the two criteria dicts is supplied, the function short-circuits and
returns that single screen's results directly rather than requiring both.

**Math:** No blended/weighted score — this is a strict intersection ("AND") of two
independently-filtered sets, merged on `symbol`. The merged DataFrame carries the
fundamental columns from `screen_stocks` plus `rsi` and `volume_ratio` from
`screen_by_technicals` (merge is an inner join via `pd.DataFrame.merge`, which
naturally keeps only symbols present in both). See `screen_stocks` and
`screen_by_technicals` above for each stage's own filter math.

**Usage:**
- `provider: AbstractDataProvider`
- `technical_criteria: dict[str, Any] | None = None` — see `screen_by_technicals`.
- `fundamental_criteria: dict[str, Any] | None = None` — see `screen_stocks`.
- `universe: str = "sp500"`
- `limit: int = 50`
- Returns: `pd.DataFrame`. Empty if fundamental criteria are given but no symbol
  passes them; if only fundamental criteria are given, returns those results
  directly (no `rsi`/`volume_ratio` columns); if only technical criteria are given,
  returns the technical screen's own columns.

Agent-facing wrapper (`screen_combined_tool`) takes both criteria as optional JSON
strings, defaults `limit=20`, runs under a 120s timeout, and returns "No stocks
matched the combined criteria." when empty.

```python
df = await screen_combined(
    provider,
    fundamental_criteria={"roe_gt": 0.15, "debt_equity_lt": 1.0},
    technical_criteria={"rsi_lt": 35},
    universe="sp500", limit=20,
)
```

---

## screen_vcp_pattern

**Agent-facing tool name:** `screen_vcp_tool`

**Purpose:** Scans a universe for Minervini-style Volatility Contraction Patterns
(VCP) — stocks that had a strong prior uptrend and are now consolidating in a
tightening, low-volume base above their 200-day moving average, i.e. the classic
pre-breakout setup used in momentum/growth trading.

**Why built this way:** Like the other pattern screens, it batch-downloads 1 year
of daily OHLCV for the whole universe via `_universe_frames` and evaluates the VCP
conditions purely from price/volume history — no external pattern-recognition
library. Each symbol is scored independently and the function requires a full
year (≥200 bars) of history before it will even attempt evaluation, since the
"prior advance" and "200-day SMA" checks both need that much lookback; thinly
traded or newly listed names are silently skipped (return `None` from
`_vcp_metrics`) rather than causing an error. Results are sorted by tightest
contraction first, on the theory that the shallowest, most contracted bases are
closest to breaking out.

**Math:** For each symbol, `close` is split into a "base" period (all but the last
63 trading days, i.e. roughly the first ~9 months of the 1-year window) and a
"recent" period (last 63 trading days, ~3 months):

- `prior_advance = base.max() / base.min() - 1` — the largest peak-to-trough
  percentage gain within the base period. Must be `>= min_prior_advance_pct`
  (default **0.30**, i.e. a 30%+ prior advance).
- `contraction = 1 - recent.iloc[-1] / recent.max()` — how far the current close
  sits below the recent-period high (a pullback/base depth measure). Must satisfy
  `0 <= contraction <= max_contraction_pct` (default **0.50**, i.e. current price
  no more than 50% below its 3-month high, and not currently making a fresh
  3-month high itself).
- `sma200 = SMA(close, 200)` — trend filter; current close must be `>` this value
  (price still in a long-term uptrend).
- `vol_dryup = mean(volume, last 10 days) / mean(volume, last 60 days)` — must be
  `< 1.0`, i.e. trading volume over the last two weeks is contracting relative to
  the last three months (classic VCP volume dry-up as the base tightens).
- `tightening = std(pct_change(recent), last 10 days) / max(std(pct_change(recent), all 63 days), 1e-9)` —
  ratio of very-recent daily-return volatility to the 3-month norm; must be
  `< 1.0`, i.e. price action in the last two weeks is calmer than the 3-month
  average (contracting volatility, the "V" in VCP).

All five conditions must hold simultaneously (`passed = advance AND contraction
AND trend AND vol_dryup AND tightening`). Passing symbols are sorted ascending by
`contraction_pct` (tightest/shallowest bases first) and truncated to `limit`.

**Usage:**
- `provider: AbstractDataProvider`
- `universe: str = "sp500"`
- `max_contraction_pct: float = 0.50` — maximum pullback from the recent (3-month)
  high.
- `min_prior_advance_pct: float = 0.30` — minimum prior uptrend size (first ~9
  months of the 1-year window).
- `limit: int = 50`
- Returns: `pd.DataFrame` with columns `symbol, price, prior_advance_pct,
  contraction_pct, volume_dryup_ratio, tightening_ratio`, sorted by
  `contraction_pct` ascending.

Agent-facing wrapper (`screen_vcp_tool`) exposes only `universe` and `limit`
(default `limit=20`) — the contraction/advance thresholds are not currently
tunable from the agent, always using the 0.50/0.30 defaults. Runs under a 120s
timeout; returns `"No VCP candidates found."` when empty.

```python
df = await screen_vcp_pattern(
    provider, universe="sp500", max_contraction_pct=0.35, min_prior_advance_pct=0.40, limit=20,
)
```

---

## screen_breakout_candidates

**Agent-facing tool name:** `screen_breakouts_tool`

**Purpose:** Finds stocks trading near their 52-week high on above-average volume
— a simple, well-known momentum/breakout setup (price strength confirmed by
participation).

**Why built this way:** Same batch-download-then-locally-evaluate approach as the
other pattern screens (`_universe_frames`), which keeps the whole-universe scan to
one network round trip. The lookback for "52-week high" is simply the max close
over whatever history was fetched (1 year via `get_batch_ohlcv(..., period="1y")`),
so it needs only 30 bars minimum (a much lower bar than VCP's 200) — a looser,
faster screen intended for a quick momentum scan rather than a strict base-pattern
detector. Results are ranked by volume ratio (strongest volume confirmation first)
rather than by proximity to the high, on the theory that volume expansion is the
more decisive breakout confirmation signal.

**Math:**
- `pct_from_high = 1 - close.iloc[-1] / close.max()` over the fetched window (≈52
  weeks) — must be `<= proximity_to_high_pct` (default **0.05**, i.e. within 5% of
  the 52-week high).
- `volume_ratio` = last-day volume ÷ mean(volume, prior 20 days) (via the shared
  `_volume_ratio` helper, needs ≥21 bars) — must be `>= volume_ratio_min` (default
  **1.5**, i.e. at least 1.5× average 20-day volume).
- Both conditions must hold (`pct_from_high <= proximity_to_high_pct AND ratio >=
  volume_ratio_min`). Sorted descending by `volume_ratio`.

**Usage:**
- `provider: AbstractDataProvider`
- `universe: str = "sp500"`
- `proximity_to_high_pct: float = 0.05` — maximum distance below the 52-week high.
- `volume_ratio_min: float = 1.5` — minimum last-day volume vs. 20-day average.
- `limit: int = 50`
- Returns: `pd.DataFrame` with columns `symbol, price, pct_from_high, volume_ratio`,
  sorted by `volume_ratio` descending.

Agent-facing wrapper (`screen_breakouts_tool`) exposes the same parameters
(default `limit=20`), runs under a 120s timeout, and returns `"No breakout
candidates found."` when empty.

```python
df = await screen_breakout_candidates(
    provider, universe="sp500", proximity_to_high_pct=0.03, volume_ratio_min=2.0, limit=20,
)
```

---

## screen_oversold_reversal

**Agent-facing tool name:** `screen_oversold_tool`

**Purpose:** Finds stocks that have sold off sharply, are technically oversold
(RSI), and are showing an early reversal candle — a mean-reversion / "buy the dip
with confirmation" setup rather than blindly buying every oversold reading.

**Why built this way:** Same batch-download pattern-screen approach as the other
pattern screens. Requiring both an oversold RSI reading *and* a same-day reversal
candle (rather than RSI alone) is a deliberate attempt to avoid catching a falling
knife — RSI alone would flag stocks that are oversold but still trending straight
down; the reversal-bar confirmation requires the price to have actually turned up
intraday. Only 30 bars of history are required (much less than VCP), making this a
fast, broad scan. Sorted by RSI ascending, i.e. the most extremely oversold names
surface first.

**Math:**
- `rsi = wilder_rsi(close)` (14-period, Wilder-smoothed) — must be `< rsi_threshold`
  (default **30.0**).
- `decline = 1 - close.iloc[-1] / close.iloc[-126:].max()` — decline from the
  6-month high (126 trading days ≈ 6 months). Must be `>= min_decline_pct` (default
  **0.20**, i.e. at least a 20% drawdown from the 6-month high).
- Reversal-bar confirmation on the most recent bar:
  - `bar_range = High - Low` of the last bar.
  - `upper_half = bar_range > 0 AND (Close - Low) / bar_range >= 0.5` — the bar
    closed in the upper half of its own high/low range.
  - Also requires `close.iloc[-1] > close.iloc[-2]` — an up day vs. the prior
    close.
  - Both must hold: `close_up_day AND upper_half`.
- All three conditions (oversold RSI, sufficient decline, reversal bar) must hold
  simultaneously. Sorted ascending by `rsi` (most oversold first).

**Usage:**
- `provider: AbstractDataProvider`
- `universe: str = "sp500"`
- `rsi_threshold: float = 30.0` — maximum RSI-14.
- `min_decline_pct: float = 0.20` — minimum decline from the 6-month high.
- `limit: int = 50`
- Returns: `pd.DataFrame` with columns `symbol, price, rsi, decline_pct`, sorted by
  `rsi` ascending.

Agent-facing wrapper (`screen_oversold_tool`) exposes the same parameters (default
`limit=20`), runs under a 120s timeout, and returns `"No oversold reversal
candidates found."` when empty.

```python
df = await screen_oversold_reversal(
    provider, universe="sp500", rsi_threshold=25.0, min_decline_pct=0.25, limit=20,
)
```

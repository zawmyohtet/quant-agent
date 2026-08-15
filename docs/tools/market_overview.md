# Market Overview Tools

`quantagent/tools/market_overview.py` — market-wide dashboards. The module
mixes two speed tiers, called out explicitly in the module docstring:

- **Fast path:** `get_market_summary` — only touches index ETFs, sector ETFs,
  and a handful of cross-asset tickers, so it completes in seconds with no
  cache warm-up.
- **Deep path:** `get_top_movers`, `get_most_active`, `generate_market_heatmap`
  — universe-scale (hundreds of symbols), read from the incremental
  `BreadthStore` (`quantagent.tools.breadth_store.BreadthStore`), which is slow
  on the first call for a given universe (must "warm" — bulk-fetch and cache
  the whole universe) and fast/incremental afterward.

Index ETF proxies used throughout (`_INDEX_ETFS`): SPY → S&P 500, QQQ →
Nasdaq 100, DIA → Dow Jones, IWM → Russell 2000.

Change-window mapping used by movers (`_MOVER_PERIOD_DAYS`): `1d`→1, `1w`→5,
`1m`→21 trading sessions.

---

## get_market_summary

**Agent-facing tool name:** `get_market_summary`

**Purpose:** A single call that rolls up index prices/trends, market-timing
signals (distribution days, follow-through day), breadth, sentiment, overall
market regime with a recommended equity exposure band, and SPY support/
resistance levels — a one-shot "what's the market doing right now" snapshot.

**Why built this way:** This function is a pure *rollup/composition* layer — it
doesn't compute any new statistics itself (aside from the small `_index_row`
helper and delegating to `detect_support_resistance`). It fans out to five
already-existing tool functions concurrently via `asyncio.gather`
(`detect_market_regime`, `count_distribution_days`, `detect_follow_through_day`,
`compute_percent_above_ma`, `compute_market_sentiment`, plus its own index ETF
batch fetch), so the wall-clock cost is the *slowest* of those calls, not their
sum. All five of those delegated calls are themselves fast-path-safe: they
default to `SPY`/`QQQ` index proxies or the `sector_etfs` universe, so
`get_market_summary` never triggers a `BreadthStore` warm-up. Because
`detect_market_regime` is called with its default `universe="sp500"`, that
component alone will silently use the sector-ETF proxy for its breadth
sub-score instead of the true S&P 500 breadth if the S&P 500 `BreadthStore` is
not already warm elsewhere in the session (see `detect_market_regime`'s own
docstring: "never blocks on a cold-cache warm-up") — this is a deliberate
degrade-gracefully trade-off, not a bug. Support/resistance is only computed
for SPY (`_spy_key_levels`), reusing the already-fetched index frame rather
than an extra fetch, and returns `{}` if SPY data happens to be missing.

**Math:** No original math here beyond `_index_row`:
- `change_1d = close[-1]/close[-2] - 1` if more than 1 bar exists, else `None`.
- `above50 = len(close) >= 50 and close[-1] > mean(close[-50:])`; same pattern
  for `above200` with a 200-bar window.
- `trend = "up"` if both above50 and above200; `"down"` if neither; otherwise
  `"mixed"`.

  Everything else (`timing`, `breadth`, `sentiment`, `regime`,
  `recommended_exposure`) is a direct pass-through of the sub-tool return
  values described in their own docs — see `market_breadth.py`'s
  `count_distribution_days`, `detect_follow_through_day`,
  `compute_percent_above_ma`, `compute_market_sentiment`, and
  `detect_market_regime` for their internal formulas (e.g. `detect_market_regime`
  combines cross-asset ratios RSP/SPY, IWM/SPY, XLY/XLP, SPY/TLT, HYG/LQD with
  index trend, VIX, and sector breadth into a 0-100 composite score; there is
  no additional weighting applied by `get_market_summary` itself — it takes
  those dicts as-is and selects a subset of keys, e.g.
  `{k: regime[k] for k in ("regime", "score", "confidence", "components")}`).

**Usage:**
- Parameters: `provider` only — no other arguments, on either the raw function
  or the agent tool wrapper.
- Returns: `dict` — `{as_of, indices: {SPY/QQQ/DIA/IWM: {name, price, change_1d,
  trend}}, timing: {distribution_days, follow_through}, breadth, sentiment:
  {score, label}, regime: {regime, score, confidence, components},
  recommended_exposure, key_levels}`. Indices missing data are simply omitted
  from the `indices` dict.
- Agent tool signature: `get_market_summary()` (no parameters), run with the
  extended `_LONG_TOOL_TIMEOUT_SEC` timeout.
- Example: `get_market_summary()` →
  `{"as_of": "2026-08-15", "indices": {"SPY": {"name": "S&P 500", "price": 512.3, "change_1d": 0.0042, "trend": "up"}, ...}, "regime": {"regime": "bull", "score": 68.2, ...}, "recommended_exposure": {"min_pct": 70, "max_pct": 100, "label": "..."}, "key_levels": {"support": [...], "resistance": [...], "current_price": 512.3}}`.

---

## get_top_movers

**Agent-facing tool name:** `get_top_movers`

**Purpose:** Returns the top N gainers or losers in a universe (S&P 500,
Nasdaq 100, or sector ETFs) over a chosen window (1 day, 1 week, or 1 month).

**Why built this way:** Deep-path: loads the whole universe's close/volume
matrices from the `BreadthStore` once (`_universe_matrices`), then ranks
in-memory with vectorized pandas ops rather than per-symbol API calls — this
is what makes "top movers across 500 stocks" tractable at all on a rate-limited
free-tier provider, at the cost of needing a warm cache. `_universe_matrices`
reports progress if the cache isn't warm yet, since a cold universe load can
take a while. Gainers vs. losers reuses one code path
(`ascending=direction=="down"`) instead of two branches — sorting ascending
for losers, descending for gainers.

**Math:**
- Change: `change = closes[-1] / closes[-(days+1)] - 1` (vectorized across all
  symbols in the universe at once), with `NaN`s dropped.
- Ranking: `change.sort_values(ascending=(direction == "down"))`. For
  `direction="up"` (gainers), sorts **descending** (largest positive change
  first); for `direction="down"` (losers), sorts **ascending** (most negative
  change first). Takes `.head(count)`.
- No minimum-move or minimum-volume threshold is applied — this is a pure
  top-N rank, not a "movers above X%" filter.
- Row assembly (`_mover_rows`, shared with `get_most_active`): `price` = latest
  close; `volume` = latest volume; `avg_volume_20d` = mean of the prior 20
  sessions' volume (`volumes.iloc[-21:-1].mean()`, i.e. excluding the current
  session), rounded to 2 decimals; symbol/value rounded to 4 decimals.

**Usage:**
- Parameters: `provider`, `universe: str = "sp500"` (`sp500`, `nasdaq100`,
  `sector_etfs`), `direction: str = "up"` (`up`=gainers, `down`=losers),
  `count: int = 10`, `period: str = "1d"` (`1d`, `1w`, `1m`).
- Returns: `pd.DataFrame` with columns `symbol`, `price`, `change_pct`,
  `volume`, `avg_volume_20d`. Empty DataFrame if the universe has ≤ `days` bars
  of history or is empty.
- Agent tool signature: `get_top_movers(universe: str = "sp500", direction: str = "up", count: int = 10, period: str = "1d")`,
  run with `_WARMUP_TIMEOUT_SEC` (accommodates a cold-cache warm-up); returns
  `"No mover data available."` when empty.
- Example: `get_top_movers(universe="sp500", direction="up", count=5, period="1w")` →
  rows like `{"symbol": "NVDA", "price": 128.44, "change_pct": 0.0931, "volume": 5.2e7, "avg_volume_20d": 4.1e7}`.

---

## get_most_active

**Agent-facing tool name:** `get_most_active`

**Purpose:** Returns the N most actively traded stocks in a universe, ranked
by how far today's volume is above its 20-day average — i.e. relative volume
surges, not raw share count.

**Why built this way:** Deliberately ranks by *volume ratio* (today vs. 20-day
average) rather than raw volume, so it surfaces stocks with unusual activity
(a signal of news/catalysts) instead of always returning the same handful of
mega-cap, naturally high-volume names. Shares the `_universe_matrices` /
`_mover_rows` plumbing with `get_top_movers` for consistency and code reuse.

**Math:**
- `avg20 = volumes.iloc[-21:-1].mean()` (trailing 20 sessions, excluding
  today), per symbol.
- `ratio = volumes[-1] / avg20.where(avg20 > 0)` — guards against
  division by zero/negative by masking non-positive averages to `NaN` first
  (via `.where`), then drops `NaN`s.
- Ranking: `ratio.sort_values(ascending=False).head(count)` — highest
  volume-vs-average ratio first. No minimum ratio threshold is enforced; it is
  a pure top-N by ratio.
- Requires at least 21 rows of volume history (`len(volumes) < 21` → empty
  result), since the 20-day average needs a full window.

**Usage:**
- Parameters: `provider`, `universe: str = "sp500"` (`sp500`, `nasdaq100`,
  `sector_etfs`), `count: int = 10`.
- Returns: `pd.DataFrame` with columns `symbol`, `price`, `volume_ratio`,
  `volume`, `avg_volume_20d`. Empty if volumes are empty or under 21 rows.
- Agent tool signature: `get_most_active(universe: str = "sp500", count: int = 10)`,
  run with `_WARMUP_TIMEOUT_SEC`; returns `"No volume data available."` when
  empty.
- Example: `get_most_active(universe="sp500", count=5)` → rows like
  `{"symbol": "TSLA", "price": 245.10, "volume_ratio": 3.42, "volume": 1.8e8, "avg_volume_20d": 5.3e7}`.

---

## generate_market_heatmap

**Agent-facing tool name:** `generate_market_heatmap`

**Purpose:** Produces a hierarchical (sector → industry → symbol, or
industry → symbol) heatmap of a chosen metric across a universe, sized by
dollar volume — the data behind a typical market-heatmap visualization
(think Finviz-style sector map), or a compact per-group summary when accessed
through the agent.

**Why built this way:** Deep-path like the movers tools: loads the universe
once from `BreadthStore`, plus classifies every symbol into sector/industry
via the shared `classify_symbols` helper from `sector_analysis.py` (reused
rather than duplicated), so it composes with that module instead of
reimplementing classification. "Size" deliberately uses **20-day average
dollar volume** (`price × volume`, mean over the trailing 20 sessions) as a
market-cap proxy, because the module docstring notes market cap itself is
"not stored" by the data layer — dollar volume is the closest available proxy
for a size-weighted heatmap tile. The raw function returns the full nested
tree, but the agent-facing wrapper (`_summarize_heatmap` /
`_generate_market_heatmap` in `tools_registry.py`) flattens and reduces each
group down to `n_symbols`, `mean_value`, and just the top-3 `largest` members
by size — because the full per-symbol tree for hundreds of stocks would be far
too large/noisy for an LLM context window. Symbols with unclassifiable
sector/industry are grouped under `"Unknown"` rather than dropped, so nothing
silently disappears from the heatmap.

**Math:**
- Per-symbol value (`_heatmap_value`, shared logic with sector_analysis's
  heatmap metrics but a separate implementation for the universe path):
  - `performance`: `close[-1]/close[-2] - 1` (needs > 1 bar).
  - `volatility`: `std(pct_change()[-21:]) * sqrt(252)` (needs ≥ 5 return obs).
  - `volume`: `avg = mean(volume[-21:-1])` (needs ≥ 21 bars); `value = volume[-1]/avg`
    if `avg` truthy (nonzero) else `None`.
  - `rsi`: `wilder_rsi(close)` — Wilder-smoothed RSI-14: gains/losses via
    `close.diff()`, each side smoothed with `ewm(alpha=1/14, adjust=False)`,
    `RSI = 100 - 100/(1 + avg_gain/avg_loss)`, returns 100.0 if average loss is
    exactly 0; needs ≥ 15 bars.
  - Raises `ValueError` for unknown metrics.
- Cell size (`_heatmap_cell`): `dollar = mean(close[-20:] * volume[-20:])`
  (element-wise price×volume per day, averaged over the trailing 20 sessions),
  rounded to 2 decimals; cell skipped entirely if value is `None` or volume
  data is missing.
- Grouping (`_place_cell`): if `group_by="sector"`, nests
  `groups[sector][industry][symbol] = {value, size}` (3 levels); if
  `group_by="industry"`, nests `groups[industry][symbol] = {value, size}`
  (2 levels). Sector/industry default to `"Unknown"` when the classification
  lacks that field.
- Agent-facing summarization (`_summarize_heatmap`, in `tools_registry.py`):
  per top-level group, flattens all nested symbol cells, computes
  `mean_value = mean(all cell values in the group)` (simple unweighted mean —
  not dollar-volume-weighted) and `largest` = the top 3 symbols by `size`
  (dollar volume) descending.

**Usage:**
- Parameters: `provider`, `universe: str = "sp500"` (`sp500`, `nasdaq100`),
  `metric: str = "performance"` (`performance`, `volume`, `volatility`, `rsi`),
  `group_by: str = "sector"` (`sector` or `industry`).
- Returns (raw function): `dict` — `{metric, group_by, as_of, groups: <nested
  dict ending in {symbol: {value, size}}>}`. Empty `groups: {}` if the universe
  has no data. Raises `ValueError` for an unknown `group_by`.
- Returns (agent tool, after `_summarize_heatmap`): `dict` — `{metric,
  group_by, groups: {group_name: {n_symbols, mean_value, largest: [{symbol,
  value}, ...up to 3]}}}`.
- Agent tool signature: `generate_market_heatmap(universe: str = "sp500", metric: str = "performance", group_by: str = "sector")`,
  run with `_WARMUP_TIMEOUT_SEC`.
- Example: `generate_market_heatmap(universe="sp500", metric="performance", group_by="sector")` →
  `{"metric": "performance", "group_by": "sector", "groups": {"Technology": {"n_symbols": 78, "mean_value": 0.0134, "largest": [{"symbol": "AAPL", "value": 0.0091}, {"symbol": "MSFT", "value": 0.0122}, {"symbol": "NVDA", "value": 0.0287}]}, ...}}`.

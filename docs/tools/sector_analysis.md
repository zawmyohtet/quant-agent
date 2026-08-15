# Sector Analysis Tools

`quantagent/tools/sector_analysis.py` — fast-path sector and industry analysis
built on the 11 SPDR sector ETFs (`quantagent.tools.universe.SECTOR_ETFS`). Every
function that only needs sector-level data works from a single batch download
of 2 years of daily OHLCV for those 11 ETFs (`_fetch_sector_frames`), so it runs
on the free tier without warming the universe-scale `BreadthStore`. Only
`get_industry_performance` drops to individual-stock data, because industry
detail does not exist at the ETF level.

Sector-to-ETF mapping (`SECTOR_ETFS`): Technology→XLK, Healthcare→XLV,
Financials→XLF, Consumer Discretionary→XLY, Consumer Staples→XLP, Energy→XLE,
Industrials→XLI, Materials→XLB, Real Estate→XLRE, Utilities→XLU, Communication
Services→XLC.

Cyclical vs. defensive grouping used by rotation detection:
- `CYCLICAL_SECTORS`: Technology, Consumer Discretionary, Financials,
  Industrials, Materials, Communication Services, Energy, Real Estate
- `DEFENSIVE_SECTORS`: Consumer Staples, Utilities, Healthcare

Common period-to-trading-days mapping (`_PERIOD_DAYS`) used across these tools:
`1d`→1, `1w`→5, `1m`→21, `3m`→63, `6m`→126, `1y`→252 sessions.

---

## get_sector_performance_ranked

**Agent-facing tool name:** `get_sector_performance_ranked`

**Purpose:** Ranks all 11 GICS sectors by trailing performance across one or
more timeframes (1d through 1y), so an agent or user can see at a glance which
sectors are leading or lagging the market right now.

**Why built this way:** Uses the 11 sector SPDR ETFs as liquid, free-tier proxies
for each GICS sector instead of computing a true cap-weighted sector index from
constituents — this keeps the whole function to a single batch OHLCV fetch
(2 years, 11 symbols) with no universe warm-up. Ranking is done by *average
rank across periods* rather than by any single period's return, so a sector
that is consistently strong across multiple timeframes outranks one that is
merely a short-term spike. Sectors with missing/empty data are silently
skipped rather than erroring.

**Math:**
- Period return: `_period_return(close, days) = close[-1] / close[-(days+1)] - 1`,
  rounded to 4 decimals; returns `None` if the series has `days` bars or fewer
  (guarantees the [-(days+1)] index is valid).
- Per-period rank: for each requested period column, `DataFrame.rank(ascending=False)`
  (rank 1 = best/highest return in that period; ties resolved by pandas'
  default averaging method).
- Overall rank: `avg_rank = mean of per-period ranks (row-wise)`, then
  `rank = avg_rank.rank(method="first")` cast to int — rank 1 is the sector
  with the best (lowest) average per-period rank; `method="first"` breaks ties
  by row order so ranks are always unique integers 1..N.
- Final rows are sorted ascending by `rank`.

**Usage:**
- Parameters: `provider` (data provider, injected by the agent registry),
  `periods: list[str] | None` — subset of `1d, 1w, 1m, 3m, 6m, 1y`; defaults to
  all six.
- Returns: `pd.DataFrame` with columns `sector`, `etf`, one column per requested
  period (decimal return, e.g. `0.0231` = +2.31%), and `rank` (int, 1 = best).
  Empty DataFrame if no sector data is available.
- Agent tool signature: `get_sector_performance_ranked(periods: str = "")` where
  `periods` is a comma-separated string (e.g. `"1m,3m,6m"`); empty string uses
  all six periods. Returns the DataFrame as a JSON records string.
- Example: `get_sector_performance_ranked(periods="1m,3m")` → rows like
  `{"sector": "Technology", "etf": "XLK", "1m": 0.0512, "3m": 0.1183, "rank": 1}`.

---

## get_industry_performance

**Agent-facing tool name:** `get_industry_performance`

**Purpose:** Drills one level below sector into GICS industries (e.g. within
"Technology": Semiconductors, Software, IT Services), ranking industries within
a chosen sector by 1-month and 3-month average returns.

**Why built this way:** This is the one function in the module that cannot stay
on the fast ETF-only path, because industry-level SPDR ETFs don't cover the
full universe — it has to classify individual stocks (default: S&P 500
constituents, via `screener._fetch_universe_tickers("sp500")`) into
sector/industry using the provider's classification endpoint, then fetch OHLCV
per stock. Classification is delegated to `classify_symbols`, which caches each
symbol's sector/industry for 7 days so repeat calls (even for a different
sector) are fast after the first cold run. The docstring explicitly warns a
cold cache can take minutes on free-tier providers because it classifies the
*entire* passed-in universe up front, not just the target sector.

**Math:**
- Sector filter: keeps symbols where `classification["sector"].lower() == sector.lower()`
  and `industry` is present.
- Per-symbol returns: `_period_return` for `1m` (21 sessions) and `3m` (63
  sessions), same formula as above.
- Industry aggregation (`_aggregate_industry_returns`): groups by `industry`,
  computing `n_stocks` (count), and the **mean** of each stock's `1m` and `3m`
  return within that industry group, rounded to 4 decimals.
- Rank: `rank = grouped["3m"].rank(ascending=False, method="first")` — ranked
  purely on 3-month average return, not 1-month, with ties broken by row order.
  Sorted ascending by rank.

**Usage:**
- Parameters: `provider`, `sector: str` (provider taxonomy name, e.g.
  "Technology", "Healthcare", "Financials" — must match the classification
  source's naming), `symbols: list[str] | None` (universe to classify; defaults
  to S&P 500).
- Returns: `pd.DataFrame` with columns `industry`, `n_stocks`, `1m`, `3m`,
  `rank`. Empty DataFrame if no members found in that sector.
- Agent tool signature: `get_industry_performance(sector: str)` — no `symbols`
  override exposed to the agent (always classifies the S&P 500). Uses an
  extended timeout (`_LONG_TOOL_TIMEOUT_SEC`) because of the classification
  cost. Returns `"No industry data found for sector: {sector}"` when empty.
- Example: `get_industry_performance(sector="Technology")` → rows like
  `{"industry": "Semiconductors", "n_stocks": 34, "1m": 0.041, "3m": 0.089, "rank": 1}`.

---

## classify_symbols

**Agent-facing tool name:** Not exposed as an agent tool (internal helper —
confirmed absent from `quantagent/agent/tools_registry.py`'s imports and tool
list; it is only called internally by `get_industry_performance` and by
`generate_market_heatmap` in `market_overview.py`).

**Purpose:** Classifies a list of symbols into `{sector, industry}` via the
data provider, with a 7-day cache and bounded concurrency, so downstream
industry/sector grouping doesn't need to hit the provider once per symbol on
every call.

**Why built this way:** Classification calls are typically the slowest/most
rate-limited provider endpoint, so results are cached per-symbol for 7 days
(`_CLASSIFICATION_TTL_SEC = 7 * 24 * 3600`) using `DataCache`, keyed
`classification:{symbol}`. Concurrency is capped at 8 simultaneous in-flight
requests via `asyncio.Semaphore(8)` to stay within free-tier rate limits while
still parallelizing the cold-cache case. Progress is reported every 25 newly
fetched (not cached) symbols via `report_progress`, since a cold run over
hundreds of symbols can otherwise look hung. Per-symbol classification failures
are caught and logged as warnings rather than aborting the whole batch — a few
missing symbols degrade gracefully rather than failing the entire call.

**Math:** None — this is data classification/caching plumbing, not a
quantitative computation.

**Usage:**
- Parameters: `provider`, `symbols: list[str]`.
- Returns: `dict[str, dict]` mapping symbol to its classification dict (at
  least `sector` and `industry` keys, provider-dependent); symbols whose
  classification failed are simply absent from the result.
- Example (internal call): `classify_symbols(provider, ["AAPL", "MSFT", "XOM"])`
  → `{"AAPL": {"sector": "Technology", "industry": "Consumer Electronics"}, ...}`.

---

## compute_sector_relative_strength

**Agent-facing tool name:** `compute_sector_relative_strength`

**Purpose:** Measures how much each sector is outperforming or underperforming
a benchmark (default SPY) over a chosen window, and whether that
outperformance is currently improving or fading.

**Why built this way:** Relative strength (RS) is computed as a simple ratio of
cumulative returns over the window rather than a full RS *line* (a
continuously plotted price ratio series) — this keeps the calculation O(1) per
sector per call instead of maintaining/plotting a time series, which fits the
tool's "single JSON-friendly snapshot" design. Benchmark data is fetched in the
same batch call as the sector ETFs (`_fetch_sector_frames(provider, extra=[benchmark])`)
so there's no extra round trip. Trend classification reuses the same
`_relative_strength` function twice (now vs. 21 sessions ago) instead of a
separate momentum calculation, keeping the "trend" signal consistent with the
"ratio" signal.

**Math:**
- RS ratio (`_relative_strength`): 
  `sym_ret = close[-1] / close[-(days+1)]`,
  `bench_ret = bench[-1] / bench[-(days+1)]`,
  `rs_ratio = round(sym_ret / bench_ret, 4)`.
  This is a ratio of *gross* returns (price relatives, e.g. 1.05 for +5%), not
  a difference of percentage returns. `rs_ratio > 1` means the sector
  outperformed the benchmark over the window; `< 1` means it underperformed.
  Returns `None` if either series has ≤ `days` bars, or if `bench_ret == 0`
  (avoids division by zero).
- Trend (`_rs_trend`): recomputes RS on data truncated 21 sessions earlier
  (`close.iloc[:-21]`, `bench.iloc[:-21]`) to get `rs_prev`, then
  `delta = rs_now - rs_prev`. `delta > 0.01` → `"improving"`; `delta < -0.01` →
  `"deteriorating"`; otherwise `"neutral"`. Note this 21-session comparison
  offset is fixed regardless of the chosen RS `period`.
- Rank: `rs_rank = rs_ratio.rank(ascending=False, method="first")` — rank 1 is
  the highest RS ratio; sorted ascending by `rs_rank`.

**Usage:**
- Parameters: `provider`, `sectors: list[str] | None` (default: all 11),
  `benchmark: str = "SPY"`, `period: str = "3m"` (one of `1w, 1m, 3m, 6m, 1y`
  — note `1d` is not a valid RS period; only the keys with at least a several
  day lookback are meaningful here).
- Returns: `pd.DataFrame` with columns `sector`, `etf`, `rs_ratio`
  (>1 = outperforming), `trend` (`improving`/`deteriorating`/`neutral`),
  `rs_rank`. Empty if benchmark data or all sector data is missing.
- Agent tool signature: `compute_sector_relative_strength(benchmark: str = "SPY", period: str = "3m")`
  — the `sectors` filter is not exposed to the agent (always all 11 sectors).
- Example: `compute_sector_relative_strength(benchmark="SPY", period="1m")` →
  rows like `{"sector": "Energy", "etf": "XLE", "rs_ratio": 1.0421, "trend": "improving", "rs_rank": 1}`.

---

## detect_sector_rotation

**Agent-facing tool name:** `detect_sector_rotation`

**Purpose:** Identifies which sectors are currently leading/lagging and
improving/deteriorating in relative strength, derives an overall risk-on vs.
risk-off rotation signal, and estimates which phase of the economic cycle the
market is behaving like.

**Why built this way:** Rather than a single "rotation score," the function
composes several independent signals from the same underlying RS momentum data
(`_sector_rs_stats`) so the caller gets a fuller picture: which 3 sectors are
strongest/weakest by absolute RS (`leading_sectors`/`lagging_sectors`), which
sectors' RS is accelerating/decelerating regardless of absolute rank
(`improving_sectors`/`deteriorating_sectors`), a binary macro read
(`rotation_signal`) built from the pre-defined cyclical/defensive sector sets in
`quantagent.tools.universe`, and a `cycle_phase` guess built from a hand-coded
lookup table of which sectors historically lead each phase
(`_CYCLE_PHASE_LEADERS`) — this table is an explicit historical heuristic, not
learned from data, and is documented in-code as such ("Sectors that
historically lead each economic cycle phase"). All of it derives from one
shared batch fetch of sector + SPY data, keeping this a fast-path,
single-round-trip tool.

**Math:**
- Per-sector stats (`_sector_rs_stats`): `half = max(lookback_days // 2, 1)`.
  `rs = _relative_strength(close, bench_close, lookback_days)` (same ratio
  formula as above, using the full `lookback_days` window). `rs_half_ago` is
  the same RS ratio computed on data truncated `half` sessions from the end
  (`close.iloc[:-half]`, `bench_close.iloc[:-half]`). `momentum = round(rs - rs_half_ago, 4)`
  — the *change* in RS ratio over the first half of the lookback window versus
  now. Sectors missing either value are dropped.
- Leading/lagging: sectors sorted descending by `rs` (absolute RS ratio,
  *not* momentum); `leading_sectors` = top 3, `lagging_sectors` = bottom 3
  (`ranked[-3:]`).
- Improving/deteriorating: `improving_sectors` = sectors with `momentum > 0.02`;
  `deteriorating_sectors` = sectors with `momentum < -0.02`. These are
  independent thresholds from leading/lagging and can overlap arbitrarily.
- Rotation signal (`_rotation_signal`): `spread = mean(momentum for cyclical sectors) - mean(momentum for defensive sectors)`
  using the fixed `CYCLICAL_SECTORS`/`DEFENSIVE_SECTORS` sets from
  `quantagent.tools.universe`. `spread > 0.01` → `"risk-on"` (cyclicals gaining
  RS momentum faster than defensives); `spread < -0.01` → `"risk-off"`;
  otherwise `"neutral"`. Returns `"neutral"` if either group is empty (missing
  data).
- Cycle phase (`_cycle_phase`): builds `strong_sectors = set(leading_sectors) | set(improving_sectors)`,
  then for each of the 4 phases in `_CYCLE_PHASE_LEADERS` counts
  `len(strong_sectors & phase_leaders)`. Picks the phase with the highest
  count (ties broken alphabetically by phase name via `max(scores, key=lambda p: (scores[p], p))`);
  defaults to `"mid-expansion"` if no phase scores > 0.
  Phase leader sets: `early-recovery` = {Financials, Consumer Discretionary,
  Real Estate, Industrials}; `mid-expansion` = {Technology, Communication
  Services, Industrials}; `late-cycle` = {Energy, Materials, Consumer Staples,
  Healthcare}; `recession` = {Utilities, Consumer Staples, Healthcare}.

**Usage:**
- Parameters: `provider`, `lookback_days: int = 90` (RS window in calendar/
  trading sessions; "half" of this is used for the momentum comparison).
- Returns: `dict` with `leading_sectors`, `lagging_sectors`, `improving_sectors`,
  `deteriorating_sectors` (lists of sector names), `rotation_signal`
  (`risk-on`/`risk-off`/`neutral`), `cycle_phase` (`early-recovery`/
  `mid-expansion`/`late-cycle`/`recession`), `as_of` (ISO date). Returns
  `{"error": "benchmark data unavailable"}` or
  `{"error": "sector data unavailable"}` on missing data instead of raising.
- Agent tool signature: `detect_sector_rotation(lookback_days: int = 90)`.
- Example: `detect_sector_rotation(lookback_days=90)` →
  `{"leading_sectors": ["Energy", "Financials", "Industrials"], "lagging_sectors": [...], "rotation_signal": "risk-on", "cycle_phase": "early-recovery", "as_of": "2026-08-15"}`.

---

## get_sector_etf_heatmap

**Agent-facing tool name:** Not exposed as an agent tool. Confirmed by
`grep -n "sector_analysis\|get_sector_etf_heatmap" quantagent/agent/tools_registry.py`:
the module's import block only pulls in `compute_sector_relative_strength`,
`detect_sector_rotation`, `get_industry_performance`, and
`get_sector_performance_ranked` from `quantagent.tools.sector_analysis` — there
is no `_get_sector_etf_heatmap` wrapper function, no `@tool` decoration, and no
entry in the `build_tool_registry` list. **This function is not agent-callable
today**; it would need to be imported, wrapped in a `_bind_provider(...)` entry,
and added to the registry list to become available to the agent.

**Purpose:** Produces a single-metric heatmap snapshot across all 11 sector
ETFs — performance, volume-vs-average, volatility, or RSI — for visualization
or programmatic use outside the agent's tool surface.

**Why built this way:** Reuses the same `_fetch_sector_frames` batch fetch as
the other sector functions and a small pluggable metric-function dispatch table
(`_HEATMAP_METRICS`) so adding a new heatmap metric only requires adding one
function and one dict entry, not touching the control flow. Sectors with
missing data are dropped rather than raising, matching the module's general
degrade-gracefully pattern.

**Math (per `metric`):**
- `performance`: 1-day return, i.e. `_period_return(close, 1)` = `close[-1]/close[-2] - 1`.
- `volume`: `avg = mean(volume[-21:-1])` (prior 20 sessions, excluding today);
  `value = volume[-1] / avg` if `avg > 0` else `None` — today's volume as a
  multiple of the trailing 20-day average.
- `volatility`: 21-session daily returns' standard deviation, annualized:
  `std(pct_change()[-21:]) * sqrt(252)`; requires at least 5 non-null return
  observations, else `None`.
- `rsi`: RSI-14 via `compute_indicators(df, ["rsi_14"])`, taking the latest
  `RSI_14` value; requires at least 15 rows of data.
  All values rounded to 4 decimals where applicable.
- Raises `ValueError` for any `metric` not in `{performance, volume, volatility, rsi}`.

**Usage:**
- Parameters: `provider`, `metric: str = "performance"` (one of `performance`,
  `volume`, `volatility`, `rsi`).
- Returns: `dict` — `{metric, as_of (ISO date), sectors: {sector_name: {etf, value}}}`.
- Example (direct Python call, not agent-invokable):
  `await get_sector_etf_heatmap(provider, metric="volatility")` →
  `{"metric": "volatility", "as_of": "2026-08-15", "sectors": {"Technology": {"etf": "XLK", "value": 0.1832}, ...}}`.

---

## compute_sector_correlation

**Agent-facing tool name:** Not exposed as an agent tool. Same grep confirms
`compute_sector_correlation` is never imported into
`quantagent/agent/tools_registry.py` and has no wrapper or registry entry.
**Not agent-callable today.**

**Purpose:** Produces a pairwise correlation matrix of daily returns across all
11 sector ETFs over a chosen lookback window, useful for diversification/
concentration analysis outside the agent surface.

**Why built this way:** Built on the same shared sector-ETF batch fetch as the
rest of the module; uses pandas' built-in `DataFrame.corr()` on daily percentage
returns rather than a custom correlation routine, keeping the implementation
minimal. Sectors with missing/empty frames are simply excluded from the closes
dict comprehension rather than raising.

**Math:**
- Closes are sliced to the trailing `days + 1` bars (`_PERIOD_DAYS[period]`),
  turned into daily percentage returns via `pct_change().dropna()`, and
  correlated with pandas' Pearson `DataFrame.corr()`, rounded to 4 decimals.
- Standard Pearson correlation coefficient — no lag/lead adjustment, no
  shrinkage.

**Usage:**
- Parameters: `provider`, `period: str = "6m"` (one of `1m, 3m, 6m, 1y`).
- Returns: `pd.DataFrame` indexed and columned by sector name, symmetric,
  diagonal = 1.0, off-diagonal in `[-1, 1]`. Empty DataFrame if no sector data.
- Example (direct Python call, not agent-invokable):
  `await compute_sector_correlation(provider, period="3m")` → a
  11x11 DataFrame, e.g. `df.loc["Technology", "Communication Services"] == 0.87`.

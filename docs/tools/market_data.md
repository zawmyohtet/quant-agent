# `quantagent/tools/market_data.py`

Thin async pass-through layer between the agent/workflow tool surface and
whichever `AbstractDataProvider` implementation is currently active (e.g. a
yfinance-backed provider or another configured data source). Every function
here has the same shape: normalize inputs slightly (mostly upper-casing
symbols), forward the call to the corresponding method on `provider`, and
return whatever the provider gives back untouched. There is no analytical
logic in this module — all math/derivation happens either inside the
provider implementation or in downstream tools that consume these results
(e.g. `quantagent/tools/workflows.py`, `market_overview.py`,
`sector_analysis.py`).

Because every function takes `provider: AbstractDataProvider` as its first
argument, they can all be registered directly in
`quantagent.tools.workflows.STEP_REGISTRY` and used as workflow steps, in
addition to being wrapped as agent tools in `tools_registry.py`.

---

## get_ohlcv

**Agent-facing tool name:** Not wrapped 1:1 — consumed internally by the
`get_ohlcv_data` agent tool (`_get_ohlcv_data` in
`quantagent/agent/tools_registry.py`), which calls this function and then
reduces the returned DataFrame to a small JSON summary (bar count, latest
close/volume, date range) rather than returning the raw frame. It is also
used directly (not through an agent tool) inside several other tool modules
that need the full price history, e.g. `_compute_technical_indicators`,
pattern/support-resistance detection, and workflow steps.

**Purpose:** Fetch OHLCV (open/high/low/close/volume) price history for one
symbol over a given period/interval.

**Why built this way:** Kept intentionally provider-agnostic and
side-effect-free so every downstream consumer (indicators, patterns,
screeners, workflows) shares one fetch path and one symbol-normalization
rule, rather than each caller re-implementing "upper-case the ticker before
hitting the provider."

**Math:** None — pure delegation: `provider.get_ohlcv(symbol.upper(),
period=period, interval=interval)`.

**Usage:**
```python
df = await get_ohlcv(provider, "aapl", period="1y", interval="1d")
```
- `symbol: str` — ticker, case-insensitive (upper-cased before the call).
- `period: str = "1y"` — e.g. `1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y`
  (provider-dependent; these are the values the agent tool wrapper
  documents).
- `interval: str = "1d"` — e.g. `1m, 5m, 15m, 30m, 60m, 1d, 1wk, 1mo`.
- Returns: `pd.DataFrame` indexed by timestamp with `Open/High/Low/Close/
  Volume` columns (column names as produced by the active provider).

---

## get_quote

**Agent-facing tool name:** `get_stock_quote` (via `_get_stock_quote`).

**Purpose:** Fetch the current/latest quote for a symbol.

**Why built this way:** Same one-line delegation pattern as the rest of the
module — the agent tool wrapper does nothing beyond calling this and
JSON-encoding the result, so this function is effectively the entire
implementation of the `get_stock_quote` tool.

**Math:** None — `provider.get_quote(symbol.upper())`.

**Usage:**
```python
quote = await get_quote(provider, "AAPL")
```
- `symbol: str` — ticker, case-insensitive.
- Returns: `dict` (fields determined by the active provider — typically
  price, change, volume, etc.).

---

## get_fundamentals

**Agent-facing tool name:** `get_stock_fundamentals` (via
`_get_stock_fundamentals`). Also used directly inside `stock_research`
workflows and `_compare_peers` (which fetches fundamentals for multiple
symbols and feeds them to `peer_comparison`).

**Purpose:** Fetch fundamental company data (financials/ratios/metadata,
provider-dependent) for a symbol.

**Why built this way:** Same delegation pattern; centralizing this call lets
every fundamentals-consuming tool (peer comparison, DCF, Piotroski/Altman
scoring, `stock_research` workflow) share one fetch path.

**Math:** None — `provider.get_fundamentals(symbol.upper())`.

**Usage:**
```python
fundamentals = await get_fundamentals(provider, "AAPL")
```
- `symbol: str` — ticker, case-insensitive.
- Returns: `dict` of fundamental fields (provider-dependent).

---

## get_earnings_calendar

**Agent-facing tool name:** `get_earnings_calendar` (via
`_get_earnings_calendar` — same name as the underlying function).

**Purpose:** Fetch upcoming earnings dates for a single symbol within a
lookahead window.

**Why built this way:** Kept separate from the multi-symbol,
cached/concurrent `get_earnings_calendar_range` in
`quantagent/tools/event_analysis.py` — this function is the cheap,
single-symbol, uncached case; the range/universe version handles batching
and caching itself rather than pushing that complexity into this thin
layer.

**Math:** None — `provider.get_earnings_calendar(symbol.upper(),
lookahead_days=lookahead_days)`.

**Usage:**
```python
events = await get_earnings_calendar(provider, "AAPL", lookahead_days=90)
```
- `symbol: str` — ticker, case-insensitive.
- `lookahead_days: int = 90` — how far ahead to search.
- Returns: `list[dict]` of upcoming earnings events.

---

## get_news

**Agent-facing tool name:** `get_stock_news` (via `_get_stock_news`). Also
used directly as the final step of the `stock_research` workflow.

**Purpose:** Fetch recent news headlines for a symbol over a trailing window.

**Math:** None — `provider.get_news(symbol.upper(), days=days)`.

**Why built this way:** Same thin-delegation rationale as the rest of the
module.

**Usage:**
```python
headlines = await get_news(provider, "AAPL", days=7)
```
- `symbol: str` — ticker, case-insensitive.
- `days: int = 7` — lookback window in days.
- Returns: `list[dict]` of news items (provider-dependent shape, typically
  title/source/date/url).

---

## search_symbols

**Agent-facing tool name:** `search_stock_symbols` (via
`_search_stock_symbols`).

**Purpose:** Look up ticker symbols by company name or partial query
(symbol lookup / autocomplete use case).

**Why built this way:** The only function in this module that does *not*
upper-case its input — `query` is a free-text company name/partial ticker,
not a known symbol, so normalization is left entirely to the provider.

**Math:** None — `provider.search_symbols(query)`.

**Usage:**
```python
matches = await search_symbols(provider, "apple")
```
- `query: str` — company name or partial ticker.
- Returns: `list[dict]` of candidate matches.

---

## get_sector_performance

**Agent-facing tool name:** `get_sector_performance` (via
`_get_sector_performance` — same name).

**Purpose:** Fetch performance figures across all major market sectors
(1D/1W/1M/3M/YTD returns, per the agent tool's docstring).

**Why built this way:** A raw, unranked snapshot straight from the provider
— note this is distinct from `get_sector_performance_ranked` in
`quantagent/tools/sector_analysis.py`, which is a separate function that
adds multi-timeframe ranking logic on top of provider data; this function
here is only the direct pass-through.

**Math:** None — `provider.get_sector_performance()`.

**Usage:**
```python
sectors = await get_sector_performance(provider)
```
- No parameters beyond `provider`.
- Returns: `dict` keyed by sector with return figures per timeframe.

---

## get_economic_indicators

**Agent-facing tool name:** `get_economic_indicators` (via
`_get_economic_indicators` — same name).

**Purpose:** Fetch macroeconomic indicators such as VIX, treasury yields (2Y,
10Y), S&P 500 P/E, GDP growth, CPI, and unemployment rate.

**Why built this way:** Same pass-through pattern; the agent tool's
docstring notes fields unavailable from the active provider are simply
returned as `null` rather than raising, so callers get a stable dict shape
regardless of provider coverage.

**Math:** None — `provider.get_economic_indicators()`.

**Usage:**
```python
indicators = await get_economic_indicators(provider)
```
- No parameters beyond `provider`.
- Returns: `dict` of indicator name to value (or `None` if unavailable).

---

### Summary

Every function in this module forwards directly to the equivalently-named
method on the active `AbstractDataProvider` (`quantagent/tools/providers/
base.py`), with symbol arguments upper-cased first (except
`search_symbols`, whose input is free text, not a symbol). None of them
perform validation, retries, caching, or computation themselves — those
concerns live in the provider implementations, in `quantagent/tools/cache.py`
(used by other tool modules, not this one), and in the higher-level tools
that consume this module's output.

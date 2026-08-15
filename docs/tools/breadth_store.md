# `quantagent/tools/breadth_store.py`

`BreadthStore` is an incremental, SQLite-backed cache of daily close/volume
bars for universe-level breadth math (advance/decline line, new
highs/lows, percent-above-MA, breadth thrust — see
`docs/tools/market_breadth.md`). It is infrastructure, not analytics: it
knows nothing about breadth formulas, only how to fetch, persist, and serve
close/volume history for hundreds of symbols at a time efficiently.

Storage location: **`~/.quantagent/cache/breadth.db`** (via
`quantagent.tools._paths.cache_dir()`).

**Agent exposure:** None of `BreadthStore`'s methods are directly wrapped as
`@tool`s for the LLM agent, with one partial exception: the agent tool
`warm_breadth_cache` (in `quantagent/agent/tools_registry.py`) constructs a
`BreadthStore()` and calls `.warm_up(provider, universe)` directly as a thin
pass-through, so `warm_up` is reachable by the agent under that name. `is_warm`,
`ensure`, `update`, and `load_field` are internal plumbing — called only by
`quantagent/tools/market_breadth.py` (via its own `_load_universe_closes` /
`_universe_or_proxy_closes` helpers) and never given their own agent tool
wrapper.

---

## Why an incremental cache, specifically

Breadth math is inherently universe-wide: computing "how many S&P 500 stocks
made a new 52-week high today" requires a full year of daily bars for all
~500 constituents, and the calculation is repeated on essentially every call
to `compute_advance_decline`, `compute_new_highs_lows`, `compute_breadth_thrust`,
or `compute_percent_above_ma`. Re-downloading ~500 symbols' full history from
a market data provider on every request would be:

- **Slow** — hundreds of network round-trips (or one very large batch call)
  per breadth query, incompatible with an interactive agent loop.
- **Wasteful** — the overwhelming majority of that data (all but the latest
  day or two) doesn't change between calls.
- **Rate-limit risk** — repeatedly re-pulling full history for hundreds of
  tickers is the kind of usage pattern that gets an API key throttled or
  banned.

`BreadthStore` solves this the standard way: pay a one-time, explicit "warm
up" cost (batch-fetch ~1 year of history for the whole universe, chunked),
persist it to local SQLite, and thereafter only fetch the last few days
incrementally (`update`). Downstream breadth tools then read the full
history straight out of SQLite (`load_field`), which is fast regardless of
universe size.

---

## Schema and keys

```sql
CREATE TABLE IF NOT EXISTS bars (
    universe TEXT NOT NULL,
    symbol   TEXT NOT NULL,
    date     TEXT NOT NULL,
    close    REAL NOT NULL,
    volume   REAL,
    PRIMARY KEY (universe, symbol, date)
);
CREATE TABLE IF NOT EXISTS universes (
    universe   TEXT PRIMARY KEY,
    updated_at TEXT NOT NULL
);
```

- `bars` holds one row per `(universe, symbol, date)` — the composite primary
  key doubles as the natural dedup/upsert key (`INSERT OR REPLACE`), so
  re-ingesting an already-known day for a symbol simply overwrites it rather
  than duplicating.
- The same physical symbol can appear multiple times under different
  `universe` values (e.g. `sp500` and `nasdaq100` share tickers) — rows are
  *not* deduplicated across universes, trading a little redundant storage for
  simplicity (each universe's data is self-contained and independently
  warmable/queryable).
- `universes` is a one-row-per-universe freshness marker: `updated_at` is
  stamped every time `warm_up` or `update` completes, and is the sole input
  to `is_warm`.
- Schema is applied via `executescript(_SCHEMA)` on *every* connection open
  (`CREATE TABLE IF NOT EXISTS` is idempotent), so the store self-initializes
  with no separate migration step.

---

## Concurrency and consistency handling

- Each call opens a **fresh `aiosqlite` connection** via the `_StoreConnection`
  async context manager (`_connect()`), applies the schema, does its work, and
  closes it — no long-lived connection or connection pool is kept. This
  keeps `BreadthStore` cheap to instantiate per-call (it's `BreadthStore()`,
  re-created on every tool invocation) and avoids holding a lock or
  connection across `await` points, which matters for SQLite's file-level
  locking under concurrent asyncio tasks.
- Writes (`_ingest`, `_touch`) always `INSERT OR REPLACE` and `commit()`
  immediately at the end of their `async with` block, so each write is a
  short, self-contained transaction.
- No explicit retry/backoff for `SQLITE_BUSY` — concurrent writers could in
  principle collide, but the store's access pattern (warm-up then occasional
  small incremental updates, typically serialized by the calling tool's
  provider fetch which dominates latency) makes contention unlikely in
  practice; callers that need resilience wrap store access in `try/except`
  (see `market_breadth.py`'s `_load_universe_closes`, which catches any
  exception from `store.ensure(...)` and logs+falls back rather than
  propagating).
- Freshness/consistency is time-based, not transactional: `is_warm` treats
  the store as good enough if it was touched within `max_age_days` (default
  3), regardless of which symbols were actually refreshed — the design
  favors "close enough, stay fast" over strict per-symbol staleness
  tracking.

---

## is_warm

**Agent-facing tool name:** Not exposed as an agent tool / internal
infrastructure. Called by `ensure()` and indirectly by `market_breadth.py`'s
cold/warm decision logic.

**Purpose:** Answers "is this universe's cached data still fresh enough to
use as-is?" without touching the network.

**Why built this way:** A pure metadata check (single-row lookup in
`universes`) so it's essentially instantaneous — used as the first, cheap
branch of every access path (`ensure()`) so the common case (already warm)
never pays for a symbol-list scan or a provider call.

**Math/logic:** `now(UTC) - updated_at <= timedelta(days=max_age_days)`, where
`updated_at` comes from the `universes` table; `False` (cold) if the universe
has no row at all.

**Usage:**
- Signature: `async def is_warm(self, universe: str, max_age_days: int = 3) -> bool`
- Example: `await BreadthStore().is_warm("sp500")` → `True`/`False`.
- `max_age_days` defaults to `_DEFAULT_MAX_AGE_DAYS = 3` — i.e. a universe
  warmed within the last 3 days is considered fresh and skips both warm-up
  and incremental update entirely.

---

## warm_up

**Agent-facing tool name:** `warm_breadth_cache` (thin pass-through wrapper
in `tools_registry.py` — the only `BreadthStore` method reachable from the
agent, and only indirectly).

**Purpose:** Performs the expensive, one-time (or first-time-per-universe)
bulk ingest: fetches roughly a year of daily history for every symbol in a
universe and writes it into the cache.

**Why built this way:** Chunking (`_WARM_CHUNK_SIZE = 100`) keeps each
provider call to a manageable batch size (friendlier to rate limits and
memory than one giant request for 500 symbols, and than 500 individual
requests), while still batching many symbols per network round-trip.
Progress is reported chunk-by-chunk via `report_progress` (so a slow,
multi-minute warm-up in an interactive TUI/agent session shows visible
progress rather than looking hung) and logged via `logger.info`. The whole
operation is deliberately allowed to run long — the agent tool wraps it with
a 600-second (`_WARMUP_TIMEOUT_SEC`) timeout, versus the standard 30s for
most tools and 120s for other universe-scale operations — because this is
meant to be an explicit, occasional "prime the cache" action, not something
run casually inline with every breadth query.

**Math/logic:**
- Resolves the universe's symbol list via `load_universe(universe)` (run in a
  thread since it may do network/file I/O); raises `ValueError` if the
  universe resolves to no symbols.
- Iterates the symbol list in chunks of 100, calling
  `provider.get_batch_ohlcv(chunk, period=period)` (default `period="1y"`)
  per chunk, and ingesting each chunk's frames via `_ingest` (upsert into
  `bars`).
- After all chunks are ingested, stamps the universe fresh via `_touch`.
- Returns row/symbol counts for observability.

**Usage:**
- Signature: `async def warm_up(self, provider, universe: str, period: str = "1y") -> dict`
- Returns: `{universe, symbols, rows}` (symbols/rows actually fetched and
  ingested).
- Example: `await BreadthStore().warm_up(provider, "sp500")` — takes up to
  several minutes for large universes on first run; agent-facing as
  `warm_breadth_cache(universe="sp500")`.

---

## update

**Agent-facing tool name:** Not exposed as an agent tool / internal
infrastructure. Called by `ensure()` when the store has data but is stale.

**Purpose:** Cheaply refreshes an already-warmed universe by re-fetching only
the last few days for symbols already known to the store, instead of a full
re-warm.

**Why built this way:** Once a universe has a year of history cached, only
the most recent day(s) actually change day to day — pulling `period="5d"`
per already-known symbol is orders of magnitude cheaper than another full 1y
warm-up, which is the whole point of the incremental design. If the store
somehow has no known symbols yet (edge case — e.g. `is_warm` says stale but
`_has_data` also finds nothing), it transparently falls back to a full
`warm_up` rather than failing.

**Math/logic:**
- `symbols = self._known_symbols(universe)` (`SELECT DISTINCT symbol FROM
  bars WHERE universe = ?`); if empty, delegates entirely to `warm_up`.
- `provider.get_batch_ohlcv(symbols, period="5d")`, then `_ingest` (upsert —
  overlapping days from the last update are simply overwritten, which is
  correct/idempotent since `INSERT OR REPLACE` matches on the same primary
  key).
- `_touch` stamps the universe fresh again.

**Usage:**
- Signature: `async def update(self, provider, universe: str) -> dict`
- Returns: `{universe, symbols, rows}`.
- Not called directly by tools/agents — reached only via `ensure()`.

---

## ensure

**Agent-facing tool name:** Not exposed as an agent tool / internal
infrastructure (public API surface used by `market_breadth.py`).

**Purpose:** The single entry point breadth tools use to "make this universe
usable," choosing the cheapest sufficient path: no-op if warm, incremental
`update` if stale-but-populated, full `warm_up` if empty — or bail out
cleanly if warm-up isn't allowed.

**Why built this way:** Centralizes the warm/stale/cold decision tree so
callers (`market_breadth.py`) don't have to reimplement it; the
`allow_warmup` flag lets latency-sensitive callers (like
`detect_market_regime`, which must always respond promptly) opt out of ever
triggering a slow first-time warm-up, instead getting a clean `False` back
and falling through to a proxy computation.

**Math/logic (decision order):**
1. `is_warm(universe)` → return `True` (no-op).
2. else if `_has_data(universe)` (any rows exist, just stale) → run
   `update(...)`, return `True`.
3. else if not `allow_warmup` → return `False` (caller should use a proxy).
4. else → run `warm_up(...)`, return `True`.

**Usage:**
- Signature: `async def ensure(self, provider, universe: str, allow_warmup: bool = True) -> bool`
- Example (as used internally):
  `ready = await store.ensure(provider, "sp500", allow_warmup=False)` — if
  `False`, the caller falls back to the sector-ETF proxy instead of loading
  data.

---

## load_field

**Agent-facing tool name:** Not exposed as an agent tool / internal
infrastructure. Called by `market_breadth.py`'s `_load_universe_closes` (and
available for `field="volume"` though current breadth tools only read
`"close"`).

**Purpose:** Reads the cached bars for a universe and reshapes them into a
wide matrix — one row per date, one column per symbol — the exact shape
breadth math (diff, rolling max/min, cumulative sums across the whole
universe) needs.

**Why built this way:** The `bars` table is stored long/tidy
(`universe, symbol, date, close, volume`), which is the right shape for
storage (natural upsert key, no wasted columns for missing symbols/dates),
but breadth calculations need it wide (`pandas.pivot`) to vectorize
operations like `.diff()` or `.rolling()` across all symbols at once. This
function is the single place that reshape happens, keeping storage and
computation concerns separate. Returns an empty `DataFrame` (rather than
raising) when there's no data at all, so callers can check `.empty` and
degrade gracefully — matching the same "fail soft" pattern used throughout
`market_breadth.py`.

**Math/logic:**
- Selects `date, symbol, <field>` for the universe from `bars` (field must be
  `"close"` or `"volume"`; anything else raises `ValueError`).
- `DataFrame.pivot(index="date", columns="symbol", values=field)`.
- Index coerced to a UTC-tz `DatetimeIndex`.
- If `days` is given, returns only the trailing `days` rows (`matrix.iloc[-days:]`).

**Usage:**
- Signature: `async def load_field(self, universe: str, field: str = "close", days: int | None = None) -> pd.DataFrame`
- Returns: wide `DataFrame`, index = date, columns = symbol, values = the
  requested field; empty `DataFrame` if the universe has no cached rows.
- Example: `matrix = await BreadthStore().load_field("sp500", "close")` then
  `matrix["AAPL"].pct_change()` etc.

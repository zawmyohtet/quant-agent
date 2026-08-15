# `quantagent/tools/cache.py`

Local infrastructure module: a small async, SQLite-backed key-value cache
with per-entry TTL, used to avoid redundant calls to rate-limited/slow data
providers (e.g. re-fetching an S&P 500 member's sector classification or
earnings calendar on every request). It is **not** exposed as an agent tool
— confirmed by grepping `quantagent/agent/tools_registry.py`, which never
imports or references `DataCache`. It is internal infrastructure consumed by
other tool modules: `quantagent/tools/sector_analysis.py` (caches per-symbol
industry classification) and `quantagent/tools/event_analysis.py` (caches
per-symbol earnings calendars). Those modules construct their own
`DataCache()` instances and call `get`/`set` directly; the agent never
touches the cache API.

---

## DataCache

**Agent-facing tool name:** Not exposed as an agent tool / internal
infrastructure.

**Purpose:** Provide a simple `get`/`set`/`invalidate`/`clear` cache backed
by a local SQLite file, so tool modules that need to fetch per-symbol data
across large universes (hundreds of tickers) can memoize expensive or
rate-limited provider calls instead of re-fetching on every request.

**Why built this way:** SQLite (via `aiosqlite`) gives a durable,
zero-dependency-service cache that survives process restarts (unlike an
in-memory dict) without requiring a separate cache server (unlike Redis) —
appropriate for a single-user desktop/CLI tool. The schema is created
lazily on every connection (`CREATE TABLE IF NOT EXISTS`) rather than via a
separate migration step, since there's only ever one table. Each `get`/
`set`/`invalidate`/`clear` call opens and closes its own connection
(`_connect()` returns a fresh `_CacheConnection` async context manager each
time) rather than holding one open — simplest-possible concurrency model,
trading a little per-call overhead for never having to reason about
connection lifetime or sharing across concurrent async tasks.

**Math:** No math — this is the "how it works" file, so the mechanics
are the emphasis:

- **Storage:** One SQLite table, `cache(key TEXT PRIMARY KEY, value TEXT NOT
  NULL, expires_at REAL NOT NULL)`, in a file at `db_path` (default
  `cache_dir() / "datacache.db"`, i.e. `~/.quantagent/cache/datacache.db`,
  overridable process-wide via the `QUANTAGENT_HOME` env var — see
  `quantagent/tools/_paths.py`). The parent directory is created on demand
  (`ensure_dir`) before every connection.
- **Cache key scheme:** `DataCache` itself is key-agnostic — the `key`
  passed to `get`/`set`/`invalidate` is just an opaque string chosen by the
  caller. In practice, callers namespace keys by purpose and symbol, e.g.
  `sector_analysis.py` uses `f"classification:{sym}"` and
  `event_analysis.py` uses `f"earnings_cal:{sym}"`. There is no key
  hashing, prefix enforcement, or automatic namespacing done by this
  module — collisions across call sites are avoided purely by callers
  choosing distinct prefixes by convention.
- **TTL handling:** `set(key, value, ttl=3600)` stores `expires_at =
  time.time() + ttl` (default TTL 1 hour if the caller doesn't override
  it). `get(key)` checks `expires_at <= time.time()`: if expired, it
  deletes the row on the spot and returns `None` (lazy expiry — there is no
  background sweeper; expired rows are only cleaned up the next time
  they're looked up, or via `clear()`). Real callers set much longer,
  purpose-specific TTLs — e.g. `_CLASSIFICATION_TTL_SEC = 7 * 24 * 3600`
  (one week) for sector/industry classification, and
  `_CALENDAR_TTL_SEC = 12 * 3600` (12 hours) for earnings calendars — since
  those values change slowly relative to how often they're queried.
- **Serialization (`_encode`/`_decode`):** Every value is stored as a JSON
  "envelope" string, not raw JSON of the value itself:
  - Plain values (dict/list/str/number/etc.) are wrapped as
    `{"kind": "json", "payload": value}` and stored via `json.dumps`.
  - `pandas.DataFrame` values are detected with `isinstance(value,
    pd.DataFrame)` and wrapped as `{"kind": "dataframe", "payload":
    value.to_json(orient="split", date_format="iso")}` — i.e. the
    DataFrame is serialized to JSON text (not pickled and not written as
    Parquet), using the `"split"` orientation (separate `columns`/`index`/
    `data` arrays) and ISO-formatted dates, then that JSON string is itself
    embedded as the `payload` field of the outer envelope (so a DataFrame
    round-trips as JSON nested inside JSON).
  - On read, `_decode` inspects `envelope["kind"]`: for `"json"` it returns
    `payload` as-is; for `"dataframe"` it reconstructs the frame via
    `pd.read_json(StringIO(payload), orient="split")`, and if the resulting
    index is a tz-naive `DatetimeIndex`, it localizes it to UTC
    (`tz_localize("UTC")`) — compensating for `to_json`/`read_json` losing
    timezone info on datetime indexes across the round trip.
  - This envelope scheme is why one cache table can transparently hold both
    OHLCV-style DataFrames and plain JSON documents (classification dicts,
    earnings event lists) without the caller needing to know or specify
    which kind of value is being stored.
- **Connection lifecycle:** `_CacheConnection` is a tiny async context
  manager: `__aenter__` opens an `aiosqlite.Connection` and applies
  `_SCHEMA` (`CREATE TABLE IF NOT EXISTS`), `__aexit__` closes it. Every
  public method (`get`, `set`, `invalidate`, `clear`) opens one of these,
  does its query, `commit()`s (for mutating operations), and lets the
  `async with` block close the connection.

**Usage:**
```python
from quantagent.tools.cache import DataCache

cache = DataCache()  # or DataCache(db_path=some_path) to override location

# Plain JSON value
cached = await cache.get("classification:AAPL")
if cached is None:
    info = await provider.get_industry_classification("AAPL")
    await cache.set("classification:AAPL", info, ttl=7 * 24 * 3600)  # 1 week

# DataFrame value works identically — encoding is transparent to the caller
df = await get_ohlcv(provider, "AAPL", period="1y")
await cache.set("ohlcv:AAPL:1y:1d", df, ttl=3600)
cached_df = await cache.get("ohlcv:AAPL:1y:1d")  # -> pd.DataFrame, tz-aware index

# Maintenance
await cache.invalidate("classification:AAPL")  # drop one entry
await cache.clear()                             # drop everything
```
- `DataCache(db_path: Path | None = None)` — optional explicit SQLite file
  path; defaults to `~/.quantagent/cache/datacache.db` (or
  `$QUANTAGENT_HOME/cache/datacache.db`).
- `async get(key: str) -> Any | None` — returns the decoded value, or `None`
  if the key is missing or has expired (expired rows are deleted as a side
  effect of the lookup).
- `async set(key: str, value: Any, ttl: int = 3600) -> None` — encodes and
  upserts (`INSERT OR REPLACE`) the value with `expires_at = now + ttl`
  seconds.
- `async invalidate(key: str) -> None` — deletes one key.
- `async clear() -> None` — deletes every row in the table.

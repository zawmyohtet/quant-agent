# Breadth Store

`quantagent/tools/breadth_store.py`

An incremental cache for storing daily price data (close and volume) for hundreds of stocks at once. This is the infrastructure that makes universe-level market breadth analysis fast and practical.

Stored at: `~/.quantagent/cache/breadth.db`

---

## Why This Exists

Market breadth analysis looks at the whole market — for example, "how many S&P 500 stocks made a new 52-week high today?" To answer that, you need a full year of daily price data for all 500 stocks.

Without a cache, you'd have to:
1. Download 500 stocks' price history every time you run a breadth calculation
2. Wait minutes for the downloads to complete
3. Risk hitting your data provider's rate limits
4. Waste bandwidth downloading the same historical data over and over

The BreadthStore solves this by:
1. **Warming up once** — download a year of data for the whole universe and store it locally
2. **Updating incrementally** — each subsequent run only fetches the last few days
3. **Serving from cache** — breadth calculations read directly from the local database, which is instant

---

## How It Works

### Storage Schema

The cache uses two SQLite tables:

**`bars` table** — stores daily price data:
- One row per (universe, symbol, date)
- Columns: universe, symbol, date, close, volume
- Primary key: (universe, symbol, date) — prevents duplicates

**`universes` table** — tracks freshness:
- One row per universe
- Columns: universe, updated_at
- Updated whenever data is warmed or refreshed

### The Lifecycle

**1. Warm up (first time)**
- Downloads ~1 year of daily data for all symbols in the universe
- Chunks the download into batches of 100 symbols to avoid overwhelming the provider
- Stores everything in the `bars` table
- Stamps the universe as "fresh" in the `universes` table
- Takes several minutes for large universes (S&P 500)

**2. Update (subsequent runs)**
- Checks if the universe is "warm" (updated within the last 3 days by default)
- If stale, fetches only the last 5 days of data for all symbols
- Overwrites existing rows (INSERT OR REPLACE) — idempotent and safe
- Stamps the universe as fresh again
- Takes seconds instead of minutes

**3. Load (breadth calculations)**
- Reads the cached data from the `bars` table
- Reshapes it into a wide matrix: one row per date, one column per symbol
- Returns a pandas DataFrame ready for analysis
- Instant — no network calls

---

## warm_breadth_cache

**Agent tool:** `warm_breadth_cache`

Explicitly warms the cache for a universe. This is the only BreadthStore method exposed to the agent.

### What It Does

Downloads a full year of daily price data for all symbols in a universe and stores it locally. This is a one-time (or occasional) operation that makes subsequent breadth calculations fast.

### When to Use It

- First time you want to run breadth analysis on a universe
- After a long gap (weeks/months) since the last warm-up
- When you explicitly want to refresh the cache with fresh data

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `universe` | `str` | required | Universe to warm (e.g. "sp500", "nasdaq100") |
| `period` | `str` | `"1y"` | How much history to download |

### Returns

A dictionary with:
- `universe` — which universe was warmed
- `symbols` — number of symbols cached
- `rows` — number of data rows stored

### Usage

**Python API:**
```python
store = BreadthStore()
result = await store.warm_up(provider, "sp500", period="1y")
print(f"Cached {result['symbols']} symbols, {result['rows']} rows")
```

**Agent tool:**
```
warm_breadth_cache(universe="sp500")
```

### Design Notes

**Chunked downloads:** The warm-up downloads symbols in batches of 100 to avoid overwhelming the provider. Progress is reported after each chunk so you know it's still working.

**Long timeout:** The agent tool uses a 600-second timeout (10 minutes) because warming a large universe can take several minutes. This is intentional — it's an explicit "prime the cache" action, not something that runs inline with every query.

---

## Internal Methods

These methods are used internally by the breadth analysis tools. They're not exposed to the agent, but understanding them helps you understand how the cache works.

### is_warm

Checks if a universe's cached data is still fresh (updated within the last N days).

**Parameters:**
- `universe` — universe name
- `max_age_days` — freshness threshold (default: 3 days)

**Returns:** `True` if fresh, `False` if stale or missing

**Usage:**
```python
store = BreadthStore()
if await store.is_warm("sp500"):
    print("Cache is fresh")
```

### update

Refreshes an already-warmed universe by fetching only the last 5 days of data.

**Parameters:**
- `provider` — data provider
- `universe` — universe to update

**Returns:** Dictionary with symbols and rows updated

**Usage:**
```python
store = BreadthStore()
result = await store.update(provider, "sp500")
```

### ensure

The main entry point for breadth tools. Decides whether to:
1. Do nothing (cache is warm)
2. Update incrementally (cache is stale but exists)
3. Warm from scratch (cache is empty)
4. Return False (cache is empty and warm-up not allowed)

**Parameters:**
- `provider` — data provider
- `universe` — universe to ensure
- `allow_warmup` — allow full warm-up if cache is empty (default: True)

**Returns:** `True` if data is ready, `False` if not

**Usage:**
```python
store = BreadthStore()
ready = await store.ensure(provider, "sp500", allow_warmup=False)
if not ready:
    print("Cache not ready, using proxy")
```

### load_field

Reads cached data and reshapes it into a wide matrix for analysis.

**Parameters:**
- `universe` — universe to load
- `field` — "close" or "volume" (default: "close")
- `days` — optional: only return the last N days

**Returns:** pandas DataFrame with dates as index, symbols as columns

**Usage:**
```python
store = BreadthStore()
closes = await store.load_field("sp500", "close")
# closes is a DataFrame: rows = dates, columns = symbols
# closes["AAPL"] is Apple's close price series
```

---

## Concurrency and Consistency

**Fresh connections:** Each operation opens a fresh SQLite connection, does its work, and closes it. This avoids holding locks across async operations and keeps things simple.

**Idempotent writes:** All writes use INSERT OR REPLACE, so re-ingesting the same data is safe — it just overwrites with the same values.

**Time-based freshness:** The cache doesn't track which symbols are stale — it just checks when the universe was last updated. This is simpler and "close enough" for breadth analysis, where you're looking at the big picture, not making trading decisions on individual stocks.

**No retry logic:** If a write fails due to SQLite busy (concurrent access), the caller is expected to handle it. In practice, contention is rare because breadth operations are typically serialized by the provider fetch latency.

---

## Summary

The BreadthStore is the infrastructure that makes universe-level market breadth analysis practical:

- **Warm up once** — download a year of data for the whole universe
- **Update incrementally** — subsequent runs only fetch the last few days
- **Serve from cache** — breadth calculations read locally, which is instant

Without this cache, breadth analysis would be too slow for interactive use. With it, you can analyze the entire S&P 500 in seconds after the initial warm-up.

The cache is transparent to the breadth analysis tools — they just call `ensure()` and `load_field()`, and the cache handles the rest. You only need to think about the cache when you're explicitly warming it or when you're wondering why a breadth calculation is slow (probably because the cache is cold).

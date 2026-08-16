# Data Cache

`quantagent/tools/cache.py`

A local caching system that stores data on your computer so the app doesn't have to download the same information over and over from the internet. Think of it like a notebook where you write down answers so you can look them up later instead of asking someone every time.

**Not exposed as an agent tool.** This is internal infrastructure used by other tools (like sector analysis and earnings calendars) to speed up their work. You don't interact with it directly.

---

## Why Do We Need a Cache?

When you ask QuantAgent to analyze 500 stocks, it needs to download data for each one — prices, company information, sector classifications, and more. Each download takes time and uses up your data provider's allowance (many providers limit how many requests you can make per day).

Without a cache, every time you run a screen or generate a report, the app would download all that data again, even though most of it hasn't changed since yesterday. That would be slow and wasteful.

The cache solves this by saving downloaded data to your hard drive. The next time you need the same information, the app checks the cache first. If the data is there and still fresh, it uses the cached version instantly instead of downloading it again.

---

## How the Cache Works

### Storage Location

The cache lives in a single file on your computer:

**Default location:** `~/.quantagent/cache/datacache.db`

This is a SQLite database — a lightweight, self-contained database that doesn't require any special software to run. It's just a file that stores data in an organized way.

You can change where the cache lives by setting the `QUANTAGENT_HOME` environment variable, or by passing a custom path when creating a `DataCache` object.

### What Gets Cached

The cache stores **key-value pairs** — think of it like a dictionary where each entry has:
- A **key** (a label like `"classification:AAPL"` or `"earnings_cal:MSFT"`)
- A **value** (the actual data — could be a company's sector classification, a list of earnings dates, or even a whole spreadsheet of price history)
- An **expiration time** (when the data should be considered stale)

Different tools use the cache for different purposes:

| Tool | What it caches | How long |
|------|----------------|----------|
| Sector analysis | Which sector and industry each stock belongs to | 7 days |
| Earnings analysis | Upcoming earnings dates for each stock | 12 hours |

The cache itself doesn't care what kind of data you store — it's completely generic. The tools that use it decide what to cache and for how long.

### How Expiration Works

Every cached item has an expiration timestamp. When you ask the cache for data, it checks:

1. **Does this key exist?** If not, return nothing.
2. **Has it expired?** If the current time is past the expiration time, delete the cached item and return nothing.
3. **Is it still fresh?** Return the cached data.

This is called **lazy expiration** — expired items aren't cleaned up automatically in the background. They're only removed when someone tries to access them. This keeps the cache simple and efficient.

If you want to manually clean up the cache, you can call `clear()` to delete everything, or `invalidate(key)` to delete a specific item.

### Handling Different Data Types

The cache can store two kinds of data:

1. **Regular data** — dictionaries, lists, numbers, text (anything that can be converted to JSON)
2. **DataFrames** — pandas DataFrames (the spreadsheet-like tables used throughout QuantAgent)

Both types are stored the same way from your perspective, but internally they're handled differently:

- **Regular data** is converted to JSON text and stored as-is.
- **DataFrames** are also converted to JSON, but with special handling to preserve column names, row indexes, and date/time information. When you retrieve a DataFrame, it's reconstructed exactly as it was stored, including timezone information on date columns.

You don't need to worry about these details — the cache figures out what kind of data you're storing and retrieves it in the same format.

---

## DataCache API

### Constructor

```python
DataCache(db_path: Path | None = None)
```

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `db_path` | `Path \| None` | `None` | Optional path to the SQLite database file. If `None`, uses `~/.quantagent/cache/datacache.db` (or `$QUANTAGENT_HOME/cache/datacache.db`). |

**Returns:** A new `DataCache` instance.

### Methods

#### get

```python
async get(key: str) -> Any | None
```

Retrieves a cached value by its key.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `key` | `str` | The cache key to look up |

**Returns:** The cached value (dict, list, DataFrame, etc.), or `None` if the key doesn't exist or has expired. If the item has expired, it's deleted from the cache as a side effect.

#### set

```python
async set(key: str, value: Any, ttl: int = 3600) -> None
```

Stores a value in the cache with an expiration time.

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `key` | `str` | required | The cache key (e.g. `"classification:AAPL"`) |
| `value` | `Any` | required | The value to cache (dict, list, DataFrame, etc.) |
| `ttl` | `int` | `3600` | Time-to-live in seconds (default: 1 hour) |

**Returns:** `None`

**Example:** Store a classification for 7 days:
```python
await cache.set("classification:AAPL", {"sector": "Technology", "industry": "Software"}, ttl=7*24*3600)
```

#### invalidate

```python
async invalidate(key: str) -> None
```

Deletes a specific key from the cache.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `key` | `str` | The cache key to delete |

**Returns:** `None`

#### clear

```python
async clear() -> None
```

Deletes all entries from the cache.

**Parameters:** None

**Returns:** `None`

---

## Design Decisions

### Why SQLite Instead of an In-Memory Cache?

An in-memory cache (storing data in RAM) would be faster, but it would disappear every time you close the app. You'd have to re-download everything on startup, which defeats the purpose.

SQLite gives us **persistence** — the data survives restarts, crashes, and system reboots. It's also **zero-dependency** — you don't need to install a separate database server like PostgreSQL or Redis. The SQLite library is bundled with Python, so it just works.

### Why Per-Call Connections?

Every time you access the cache (get, set, invalidate, or clear), the app opens a fresh connection to the database, does its work, and closes the connection. This might seem wasteful — wouldn't it be faster to keep a connection open?

The answer is **simplicity and safety**. QuantAgent runs many operations in parallel (downloading data for hundreds of stocks at once, for example). If we kept a single connection open, we'd have to worry about multiple threads trying to use it at the same time, which can cause errors or data corruption.

By opening and closing connections for each operation, we avoid these concurrency issues entirely. The overhead of opening a connection is tiny (microseconds), so the performance cost is negligible.

### Why Lazy Expiration?

Some caching systems run a background process that periodically scans for and deletes expired items. We chose not to do this because:

1. **Simplicity** — no background threads, no cleanup logic, no edge cases.
2. **Efficiency** — we only delete items when someone actually tries to access them. If an item is never accessed again, it just sits there harmlessly until the next cache clear.
3. **Predictability** — the cache's behavior is completely deterministic. There's no mystery about when cleanup happens.

The trade-off is that the cache file might accumulate expired items over time, taking up disk space. In practice, this isn't a problem — the cache is small (a few megabytes at most), and you can manually clear it if needed.

### Why an Envelope Format?

When storing data, the cache wraps it in a JSON "envelope" that looks like this:

```json
{"kind": "json", "payload": <your data>}
```

or for DataFrames:

```json
{"kind": "dataframe", "payload": <dataframe as JSON>}
```

This envelope tells the cache what kind of data it's storing, so it can reconstruct it correctly when you retrieve it. Without this, the cache wouldn't know whether a stored value should be returned as a dictionary, a list, or a DataFrame.

The envelope approach lets one cache table hold mixed data types transparently — you can store a company classification (dictionary) and a price history (DataFrame) in the same cache without any special handling.

---

## What This Means for You

As a user, you don't interact with the cache directly. But understanding how it works helps you understand QuantAgent's behavior:

- **First run is slow** — when you run a screen or report for the first time, the app has to download all the data from scratch. This can take a few minutes for large universes like the S&P 500.
- **Subsequent runs are fast** — the next time you run the same screen, most of the data is already cached, so it completes in seconds.
- **Data stays fresh** — the cache automatically expires old data (after 7 days for classifications, 12 hours for earnings calendars), so you're always working with reasonably current information.
- **You can clear the cache** — if you ever need to force a fresh download (for example, if you suspect the cache has stale data), you can delete the cache file or use the `clear()` method.

The cache is one of the reasons QuantAgent feels responsive after the initial setup — it's doing everything it can to avoid redundant work and give you fast answers.

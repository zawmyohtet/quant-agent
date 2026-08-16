# Universe Tools

`quantagent/tools/universe.py`

Tools for managing stock universes — the lists of symbols that screeners and breadth tools operate on. A universe defines the "search space" for analysis.

---

## Built-in Universes

QuantAgent comes with four pre-defined universes:

| Universe | Description | Source |
|----------|-------------|--------|
| `sp500` | S&P 500 constituents | Wikipedia (cached 7 days) |
| `nasdaq100` | Nasdaq 100 constituents | Wikipedia (cached 7 days) |
| `dow30` | Dow Jones 30 constituents | Wikipedia (cached 7 days) |
| `sector_etfs` | 11 GICS sector SPDR ETFs | Hardcoded list |

**Note:** `russell2000` is intentionally not offered — there's no free, reliable source for Russell 2000 constituents. It can be added with a paid data provider.

---

## Custom Universes

You can create your own custom universes — personal watchlists, thematic baskets, sector sub-slices, or any group of stocks you want to analyze together.

Custom universes are stored as JSON files at `~/.quantagent/universes/<name>.json`.

---

## list_universes

**Agent tool:** `list_universes_tool`

Lists all available universes — the four built-ins plus any custom universes you've created.

### What It Does

Returns a list of universe names you can use with screeners and breadth tools. Built-in universes are listed first, followed by custom universes in alphabetical order.

### Parameters

None.

### Returns

A list of universe names (strings).

### Usage

**Python API:**
```python
names = list_universes()
# ["sp500", "nasdaq100", "dow30", "sector_etfs", "my_watchlist", "tech_stocks"]
```

**Agent tool:**
```
list_universes_tool()
```

---

## create_universe

**Agent tool:** `create_universe_tool`

Creates a new custom universe (watchlist) or updates an existing one.

### What It Does

Takes a name and a list of symbols, validates them, and saves them as a custom universe. If a universe with that name already exists, it's overwritten (this is the update path).

### How It Works

1. **Validate name** — must be 1-64 characters, lowercase letters/digits/underscore/hyphen only, and not collide with a built-in name
2. **Normalize symbols** — strip whitespace, uppercase, deduplicate (preserving order)
3. **Validate symbols** — must have at least one non-empty symbol
4. **Save to disk** — writes JSON to `~/.quantagent/universes/<name>.json`
5. **Preserve created_at** — if updating, keeps the original creation timestamp

### Parameters

| Name | Type | Description |
|------|------|-------------|
| `name` | `str` | Universe name (lowercase, 1-64 chars, no built-in names) |
| `symbols` | `list[str]` | List of stock tickers |

### Returns

`None` (side effect: creates/updates the JSON file)

### Usage

**Python API:**
```python
create_universe("my_watchlist", ["AAPL", "MSFT", "GOOGL"])
# Creates ~/.quantagent/universes/my_watchlist.json
```

**Agent tool:**
```
create_universe_tool(name="my_watchlist", symbols="AAPL,MSFT,GOOGL")
```

The agent tool takes symbols as a comma-separated string.

### Design Notes

**Name validation:** The name pattern `^[a-z0-9_\-]{1,64}$` ensures the name is filesystem-safe (used directly as `<name>.json`) and prevents collisions with built-in universes.

**Symbol normalization:** Symbols are uppercased and deduplicated, so `["aapl", "MSFT", "aapl"]` becomes `["AAPL", "MSFT"]`. This prevents duplicates and case-sensitivity issues.

**Update semantics:** Calling `create_universe` with an existing name overwrites it but preserves the original `created_at` timestamp. There's no separate `update_universe` function — create is also update.

---

## delete_universe

**Agent tool:** `delete_universe_tool`

Deletes a custom universe.

### What It Does

Removes a custom universe's JSON file. Built-in universes cannot be deleted.

### Parameters

| Name | Type | Description |
|------|------|-------------|
| `name` | `str` | Universe name (must be custom, not built-in) |

### Returns

`None` (side effect: deletes the JSON file)

### Usage

**Python API:**
```python
delete_universe("my_watchlist")
# Deletes ~/.quantagent/universes/my_watchlist.json
```

**Agent tool:**
```
delete_universe_tool(name="my_watchlist")
```

### Design Notes

**Cannot delete built-ins:** Attempting to delete a built-in universe raises `ValueError`. Built-ins are considered part of the system, not user data.

**Clear error on missing:** If the universe doesn't exist, raises `ValueError` rather than silently succeeding. This gives clear feedback on typos.

---

## load_universe

**Agent tool:** Not exposed (internal)

Resolves a universe name to a list of ticker symbols.

### What It Does

Takes a universe name (built-in or custom) and returns the list of ticker symbols. This is the function that screeners and breadth tools call to get the symbols to analyze.

### How It Works

1. **Check if built-in** — if the name is one of the four built-ins, delegates to `builtin_universe_symbols`
2. **Otherwise, load custom** — reads the JSON file from `~/.quantagent/universes/<name>.json`
3. **Return symbols** — returns the list of ticker symbols

### Parameters

| Name | Type | Description |
|------|------|-------------|
| `name` | `str` | Universe name (built-in or custom) |

### Returns

A list of ticker symbols (strings).

### Usage

```python
tickers = load_universe("sp500")  # ~500 symbols
tickers = load_universe("my_watchlist")  # your custom list
```

### Design Notes

**Graceful failure:** If the universe doesn't exist or can't be loaded, raises `ValueError`. Screener callers catch this and degrade to an empty ticker list (logged as a warning) rather than crashing.

**Caching for built-ins:** Built-in universes are cached for 7 days to avoid hammering Wikipedia on every call. The cache is stored at `~/.quantagent/cache/universes/<name>.json`.

---

## builtin_universe_symbols

**Agent tool:** Not exposed (internal)

Resolves a built-in universe name to its list of ticker symbols.

### What It Does

For `sector_etfs`, returns the hardcoded list of 11 sector ETFs. For `sp500`, `nasdaq100`, and `dow30`, scrapes the constituent list from Wikipedia and caches it for 7 days.

### How It Works

1. **Check cache** — if a fresh cache exists (< 7 days old), use it
2. **Scrape Wikipedia** — if cache is stale or missing, scrape the Wikipedia page for the index
3. **Extract symbols** — parse the HTML table to extract ticker symbols
4. **Cache result** — save to `~/.quantagent/cache/universes/<name>.json`
5. **Return symbols** — returns the list of tickers

### Parameters

| Name | Type | Description |
|------|------|-------------|
| `name` | `str` | Built-in universe name |

### Returns

A list of ticker symbols (strings).

### Usage

```python
symbols = builtin_universe_symbols("sp500")  # ~500 symbols
etfs = builtin_universe_symbols("sector_etfs")  # 11 ETFs
```

### Design Notes

**Graceful degradation:** If the Wikipedia scrape fails (network error, layout change, etc.), falls back to the stale cache if one exists. Only returns an empty list if there's no cache at all and the scrape also fails. This ensures a week-old S&P 500 list is available even if Wikipedia is temporarily unreachable.

**Caching:** Results are cached for 7 days because index membership changes rarely. This avoids hammering Wikipedia on every screener call.

**Sector ETFs are instant:** `sector_etfs` returns a hardcoded list — no network call, no cache needed. The list essentially never changes.

---

## get_universe_metadata

**Agent tool:** Not exposed (internal)

Returns metadata about a universe — type, symbol count, and timestamps.

### What It Does

Provides information about a universe without loading the full symbol list. Useful for displaying universe information in listings or UIs.

### Parameters

| Name | Type | Description |
|------|------|-------------|
| `name` | `str` | Universe name (built-in or custom) |

### Returns

A dictionary with:
- `name` — universe name
- `type` — "builtin" or "custom"
- `symbol_count` — number of symbols
- `created_at` — creation timestamp (custom only)
- `updated_at` — last update timestamp (custom only)

### Usage

```python
metadata = get_universe_metadata("sp500")
# {"name": "sp500", "type": "builtin", "symbol_count": 503}

metadata = get_universe_metadata("my_watchlist")
# {"name": "my_watchlist", "type": "custom", "symbol_count": 3,
#  "created_at": "2026-08-01T12:00:00+00:00", "updated_at": "2026-08-01T12:00:00+00:00"}
```

---

## Summary

These universe tools help you manage the lists of stocks you analyze:

- **list_universes** — see what universes are available
- **create_universe** — create or update a custom watchlist
- **delete_universe** — remove a custom universe
- **load_universe** — resolve a universe name to symbols (internal)
- **builtin_universe_symbols** — resolve built-in universe to symbols (internal)
- **get_universe_metadata** — get info about a universe (internal)

Use these tools to:
- Create personal watchlists for the stocks you follow
- Build thematic baskets (e.g. "AI stocks", "renewable energy")
- Define sector sub-slices not covered by the built-in sector ETFs
- Manage the search space for your screens and breadth analysis

Remember: the universe you choose determines what stocks are analyzed. A screen of the S&P 500 will only find stocks in the S&P 500. If you want to analyze a different set of stocks, create a custom universe first.

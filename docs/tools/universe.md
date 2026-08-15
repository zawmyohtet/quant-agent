# Universe Tools

Source: `quantagent/tools/universe.py`

This module defines the named symbol universes that every screener and market-
breadth tool bounds its search space with. There are two kinds:

- **Built-in universes** (`sp500`, `nasdaq100`, `dow30`, `sector_etfs`) — scraped
  from Wikipedia (for the index constituents) or hardcoded (for `sector_etfs`), and
  disk-cached for 7 days under `~/.quantagent/cache/universes/`.
- **Custom universes** — user-defined symbol lists saved as JSON files under
  `~/.quantagent/universes/<name>.json`.

Note: `russell2000` is intentionally not offered — there is no free, reliable
constituent source for it; it can return with a paid data provider.

---

## builtin_universe_symbols

**Agent-facing tool name:** Not exposed as an agent tool.

**Purpose:** Resolves one of the built-in universe names (`sp500`, `nasdaq100`,
`dow30`, `sector_etfs`) to its actual list of ticker symbols, doing the Wikipedia
scrape (or returning the static sector-ETF map) and caching the result.

**Why built this way:**
- `sector_etfs` is answered instantly from the hardcoded `SECTOR_ETFS` dict (11
  GICS sector SPDR ETF tickers: XLK, XLV, XLF, XLY, XLP, XLE, XLI, XLB, XLRE, XLU,
  XLC) — no network call, no cache needed, since this list essentially never
  changes.
- `sp500`/`nasdaq100`/`dow30` constituents are scraped from their respective
  Wikipedia pages (via `pandas.read_html` against the raw response text, extracting
  the first table with a `Symbol`/`Ticker`/`" ticker"` column) since there's no free
  structured API for index membership.
- Results are cached to `~/.quantagent/cache/universes/<name>.json` for 7 days
  (`_CONSTITUENT_TTL = timedelta(days=7)`) — index membership changes rarely, so a
  week-old list is fine, and this avoids hammering Wikipedia on every screener call.
- Degradation on scrape failure is deliberately graceful: if a fresh cache exists,
  it's used; if the cache is stale but a re-scrape fails (network error, Wikipedia
  table layout change, etc.), the function falls back to the **stale cache** rather
  than raising — a week-old S&P 500 list is far more useful to a screener than a
  hard failure. Only when there is no cache at all and the scrape also fails does
  it return an empty list (callers like `_fetch_universe_tickers` treat that as "no
  tickers found" and screens return an empty DataFrame rather than erroring).
  Raises `ValueError` only for a genuinely unknown universe name.

**Math:** N/A — no scoring, pure data resolution.

**Usage:**
- `name: str` — one of `sp500`, `nasdaq100`, `dow30`, `sector_etfs`.
- Returns: `list[str]` of ticker symbols (for `sector_etfs`, ETF tickers, not
  underlying company symbols).
- Raises: `ValueError` for any name not in `{sector_etfs} ∪ _UNIVERSE_URLS.keys()`.

```python
symbols = builtin_universe_symbols("sp500")   # e.g. ["MMM", "AOS", "ABT", ...]
etfs = builtin_universe_symbols("sector_etfs")  # ["XLK", "XLV", "XLF", ...]
```

---

## list_universes

**Agent-facing tool name:** `list_universes_tool`

**Purpose:** Lists every universe name a caller can pass to a screener or
breadth tool — the four built-ins plus whatever custom universes the user has
saved — so the agent (or a user) can discover valid `universe=` values.

**Why built this way:** Built-ins are always listed first in a fixed order
(`BUILTIN_UNIVERSES = ["sp500", "nasdaq100", "dow30", "sector_etfs"]`), then custom
universes are appended alphabetically by scanning `~/.quantagent/universes/*.json`
and taking each file's stem as the name — this keeps the well-known universes at
the top regardless of how many custom ones a user has accumulated. The
agent-facing wrapper doesn't just return the plain name list; it maps each name
through `get_universe_metadata` so the LLM sees symbol counts and timestamps
without a second round trip.

**Math:** N/A.

**Usage:**
- No parameters.
- Returns: `list[str]` — built-ins first, then custom universe names sorted
  alphabetically.

Agent-facing wrapper (`list_universes_tool`) takes no arguments and returns a JSON
array of metadata objects (see `get_universe_metadata` below), one per universe
name.

```python
names = list_universes()
# ["sp500", "nasdaq100", "dow30", "sector_etfs", "my_watchlist"]
```

---

## create_universe

**Agent-facing tool name:** `create_universe_tool`

**Purpose:** Lets a user (or the agent, on the user's behalf) define a named,
reusable custom watchlist/universe of tickers that any screener or breadth tool can
then target via `universe=<name>` — e.g. a personal watchlist, a thematic basket,
or a sector sub-slice not covered by the built-ins.

**Why built this way:**
- Universe names are validated against `_NAME_PATTERN = ^[a-z0-9_\-]{1,64}$` (1-64
  chars, lowercase letters/digits/underscore/hyphen only) and rejected if they
  collide with a built-in name (`sp500`, `nasdaq100`, `dow30`, `sector_etfs`) —
  this keeps custom universes filesystem-safe (used directly as `<name>.json`) and
  prevents a user from accidentally shadowing/corrupting a built-in.
- Symbols are normalized on write: stripped of whitespace, uppercased, and
  deduplicated while preserving first-seen order (`dict.fromkeys(...)`) — so
  `["aapl", "MSFT", "aapl"]` becomes `["AAPL", "MSFT"]`. An all-empty/whitespace
  symbol list raises `ValueError` rather than silently creating an empty universe
  that would break every screener that tries to load it.
- Calling this again with the same name **overwrites** the universe (this is the
  documented update path — there's no separate `update_universe`), but it
  preserves the original `created_at` timestamp by reading it from the existing
  file before overwriting, only refreshing `updated_at`. This gives simple
  create-or-update semantics with one function.
- No hardcoded symbol-count cap — a custom universe can be as large or small as
  the caller wants (bounded only by whatever the downstream screener's own
  `max_symbols`/timeout handling can process).

**Math:** N/A.

**Usage:**
- `name: str` — must match `^[a-z0-9_\-]{1,64}$` and not be a built-in name.
- `symbols: list[str]` — raw ticker list; whitespace-stripped, uppercased,
  deduplicated on write.
- Returns: `None`. Writes/overwrites
  `~/.quantagent/universes/<name>.json` with
  `{"name", "symbols", "created_at", "updated_at"}` (ISO-8601 UTC timestamps).
- Raises: `ValueError` for an invalid name, a built-in name, or an empty/blank
  symbol list.

Agent-facing wrapper (`create_universe_tool`) takes `symbols` as a comma-separated
string (parsed via `_parse_comma_symbols`, which also strips/uppercases) and
returns the new universe's metadata (via `get_universe_metadata`) as JSON.

```python
create_universe("my_watchlist", ["aapl", "msft", "googl", "aapl"])
# -> ~/.quantagent/universes/my_watchlist.json:
# {"name": "my_watchlist", "symbols": ["AAPL", "MSFT", "GOOGL"], ...}
```

---

## load_universe

**Agent-facing tool name:** Not exposed as an agent tool directly (used
internally by every screener/breadth tool that takes a `universe=` parameter, e.g.
`screen_stocks`, `screen_by_technicals`, `screen_vcp_pattern`, etc., via
`_fetch_universe_tickers`/`_universe_frames` wrappers in `screener.py`).

**Purpose:** The single resolution point that turns any universe name — built-in
or custom — into a concrete `list[str]` of ticker symbols for a screener to
iterate over.

**Why built this way:** Dispatches on whether `name` is one of the four built-ins
(delegating to `builtin_universe_symbols`, which handles the Wikipedia-scrape +
7-day cache dance) or otherwise treats it as a custom universe filename lookup
under `~/.quantagent/universes/`. This gives every downstream tool a single,
uniform way to go from a string to a symbol list without needing to know whether
that universe is built-in or user-defined. Screener callers (see
`_fetch_universe_tickers` in `screener.py`) catch any exception this raises and
degrade to an empty ticker list (logged as a warning) rather than propagating the
error — so a typo'd universe name results in "no stocks matched" rather than a
crash.

**Math:** N/A.

**Usage:**
- `name: str` — built-in or custom universe name.
- Returns: `list[str]` of ticker symbols.
- Raises: `ValueError` if `name` is not a built-in and no matching custom universe
  file exists.

```python
tickers = load_universe("sp500")          # scraped + cached built-in
tickers = load_universe("my_watchlist")   # custom, from disk
```

---

## delete_universe

**Agent-facing tool name:** `delete_universe_tool`

**Purpose:** Removes a previously created custom universe/watchlist that is no
longer needed.

**Why built this way:** Reuses the same name validation as `create_universe`
(`_validate_name`) so built-in universes can never be deleted (attempting to
raises `ValueError` before the filesystem is touched) — built-ins are considered
part of the system, not user data. Raises rather than silently no-op-ing if the
named custom universe doesn't exist, so a caller gets clear feedback on a typo
rather than a false "success."

**Math:** N/A.

**Usage:**
- `name: str` — custom universe name (must not be a built-in).
- Returns: `None`. Deletes `~/.quantagent/universes/<name>.json`.
- Raises: `ValueError` for a built-in name or a universe that doesn't exist.

Agent-facing wrapper (`delete_universe_tool`) takes the same `name` parameter and
returns a plain confirmation string, `"Universe '<name>' deleted."`.

```python
delete_universe("my_watchlist")
```

---

## get_universe_metadata

**Agent-facing tool name:** Not exposed as its own agent tool (used internally
by `list_universes_tool` and `create_universe_tool` to build their JSON
responses).

**Purpose:** Returns descriptive metadata about a universe — whether it's
built-in or custom, how many symbols it contains, and (for custom universes) when
it was created/last updated — without needing to load and inspect the full symbol
list yourself.

**Why built this way:** Built-in universes report only `name`, `type: "builtin"`,
and `symbol_count` (computed by actually resolving `builtin_universe_symbols`,
so the count reflects the live/cached scrape, not a hardcoded number — for
`sector_etfs` this is always 11). Custom universes additionally surface
`created_at`/`updated_at` from the JSON file, since that provenance only exists
for user-created universes. This split lets the agent present built-ins and
custom universes uniformly in a single listing (as `list_universes_tool` does)
while still surfacing the extra provenance fields where they exist.

**Math:** N/A.

**Usage:**
- `name: str` — built-in or custom universe name.
- Returns: `dict`.
  - Built-in: `{"name": str, "type": "builtin", "symbol_count": int}`.
  - Custom: `{"name": str, "type": "custom", "symbol_count": int, "created_at":
    str | None, "updated_at": str | None}`.
- Raises: `ValueError` if `name` is a custom name with no matching file.

```python
get_universe_metadata("sp500")
# {"name": "sp500", "type": "builtin", "symbol_count": 503}

get_universe_metadata("my_watchlist")
# {"name": "my_watchlist", "type": "custom", "symbol_count": 3,
#  "created_at": "2026-08-01T12:00:00+00:00", "updated_at": "2026-08-01T12:00:00+00:00"}
```

# Data Providers

`quantagent/tools/providers/` is the data-source abstraction layer underneath every quant tool in the codebase. It is **not** a set of LangChain `@tool` functions the LLM calls directly — nothing in this package is ever bound into the tool registry or exposed to the agent. Instead, `market_data.py` and nearly every other module under `tools/*.py` (`technical.py`, `fundamentals.py`, `screener.py`, `breadth_store.py`, `conviction.py`, `event_analysis.py`, `risk_gate.py`, and more) accept a `provider: AbstractDataProvider` as their first argument and call methods on it. Tool functions never instantiate a provider themselves — the active provider is constructed once (via `get_active_provider(config)`) and threaded through by the caller (`tools_registry.py`'s `_bind_provider`, or the TUI's cached `get_provider()`).

This indirection is the dependency rule the rest of the architecture leans on: `tools/` never imports from `agent/`, `tui/`, or `adapter/`, and every quant function is written once against the `AbstractDataProvider` interface rather than against a specific vendor SDK. Swapping `config.provider` from `"yfinance"` to `"alpha_vantage"` or `"polygon"` changes which concrete class answers those calls, but every tool function, every unit test that uses a fake/synthetic provider, and every piece of downstream math (technical indicators, breadth, screener, conviction scoring) is unaffected because it only ever depends on the abstract contract.

## AbstractDataProvider (base contract)

`quantagent/tools/providers/base.py` defines `AbstractDataProvider(ABC)`, the interface every concrete provider must satisfy.

### Abstract methods (must be implemented by every provider)

| Method | Signature | Returns |
|---|---|---|
| `get_ohlcv` | `(symbol, period="1y", interval="1d")` | `pd.DataFrame` — columns `Open High Low Close Volume`, `DatetimeIndex` in UTC |
| `get_quote` | `(symbol)` | `dict` — current price, change_pct, volume, market_cap, bid, ask |
| `get_fundamentals` | `(symbol)` | `dict` — P/E, P/B, EV/EBITDA, ROE, ROA, debt/equity, FCF, dividend yield, EPS |
| `search_symbols` | `(query)` | `list[dict]` — `[{symbol, name, exchange}]` |
| `get_news` | `(symbol, days=7)` | `list[dict]` — `[{title, source, url, published_at, sentiment}]` |
| `get_earnings_calendar` | `(symbol, lookahead_days=90)` | `list[dict]` — `[{date, eps_estimate, eps_actual, quarter}]` |
| `get_sector_performance` | `()` | `dict` — `{sector: {1d, 1w, 1m, 3m, ytd, best_stock}}` |
| `get_economic_indicators` | `()` | `dict` — `{vix, 10y_yield, 2y_yield, sp500_pe, gdp_growth, cpi, unemployment_rate}` |

These eight cover the minimum data surface every quant tool needs regardless of vendor. A provider that can't implement one meaningfully (e.g. Polygon has no macro/econ endpoint) must still implement the method and return an all-`None`/empty shape rather than omitting it, so callers never need to branch on provider type.

### Concrete default methods (overridable)

| Method | Default behavior |
|---|---|
| `get_industry_classification(symbol)` | Returns `{"symbol": symbol, "sector": None, "industry": None}` — reports "unavailable" unless a provider overrides it with real classification data. |
| `get_earnings_history(symbol, quarters=8)` | Returns `[]` — no history unless a provider overrides it. |
| `get_batch_ohlcv(symbols, period="1y", interval="1d")` | Fans out to `get_ohlcv` per symbol under a bounded `asyncio.Semaphore(8)`, gathered via `asyncio.TaskGroup`. Symbols that raise are logged as warnings and simply omitted from the result dict — one bad symbol never fails the whole batch. |
| `get_batch_quotes(symbols)` | Same pattern as `get_batch_ohlcv`, fanning out to `get_quote` per symbol under the same bounded semaphore. |

These four have working defaults built entirely out of the abstract methods, so a minimal provider implementation (the 8 abstract methods) is automatically usable for batch/classification/history calls — just less efficiently than a provider with a native batch endpoint.

### Why built this way

- **Abstract base class, not a protocol/duck-typed convention** — every quant tool function in the codebase (`technical.py`, `screener.py`, `breadth_store.py`, `conviction.py`, etc.) is written once against `AbstractDataProvider` and works unmodified no matter which vendor is active. `ABC` + `@abstractmethod` makes the contract enforceable at class-definition time: a new provider that forgets an abstract method fails to instantiate, rather than failing at some arbitrary runtime call site three layers deep in a screener or backtest.
- **Bounded concurrency (`Semaphore(8)`) for batch defaults** — screeners and universe-wide breadth calculations can request OHLCV for hundreds of symbols at once. Firing them all concurrently would blow through per-provider rate limits (Alpha Vantage's free tier is especially strict); doing them strictly serially would be far too slow for an interactive TUI. A semaphore of 8 caps in-flight requests to a level that respects typical free/paid API rate limits while still overlapping I/O-bound network latency across symbols.
- **Standardized OHLCV shape (`Open/High/Low/Close/Volume` columns, UTC `DatetimeIndex`)** — yfinance, Alpha Vantage, and Polygon each return wildly different native schemas (different column names, tz-naive vs tz-aware indexes, adjusted vs unadjusted close, different orderings). Normalizing every provider's OHLCV output to the same column set and UTC-indexed `DataFrame` means every downstream consumer (technical indicators, backtester, breadth store) can do date-arithmetic and column access without ever checking which provider produced the data.

## YFinanceProvider

`quantagent/tools/providers/yfinance_provider.py`

**Purpose.** Wraps the `yfinance` (Yahoo Finance) Python library. It is the free, no-API-key default provider (`config.provider = "yfinance"`).

**Why built this way.** yfinance requires no signup/auth and covers all eight abstract methods plus real overrides for three of the four default methods, making it the natural zero-config default for new installs and for CI/tests.

**What it overrides vs. relies on defaults for.**
- Overrides `get_batch_ohlcv` with a single `yf.download(tickers=..., group_by="ticker", threads=True)` call instead of the base class's per-symbol semaphore loop — yfinance's own batch endpoint is more efficient and handles its own internal threading.
- Overrides `get_industry_classification` using `ticker.info["sector"]`/`["industry"]`.
- Overrides `get_earnings_history` using `ticker.earnings_dates`, filtering to events strictly before "now" and returning at most `quarters` most-recent entries.
- Relies on the base-class default for `get_batch_quotes` (no native yfinance batch-quote call is used; quotes are fetched one at a time under the shared `Semaphore(8)`).

**Data normalization details.**
- `get_ohlcv`: calls `ticker.history(period=..., interval=...)` on a thread (via `asyncio.to_thread`, since yfinance is sync), slices to the five OHLCV columns, and converts the index to UTC with `tz_convert` (yfinance's history index is already tz-aware in the exchange's local timezone).
- `get_batch_ohlcv`: `yf.download` returns either a single-level or `MultiIndex` (`ticker`, `field`) column frame depending on symbol count. `_extract_symbol_frame` branches on `isinstance(raw.columns, pd.MultiIndex)` to slice out each symbol's sub-frame (or uses the whole frame directly when there is exactly one symbol and columns are flat), then `_normalize_ohlcv_frame` restricts to the OHLCV columns, drops all-NaN rows, and localizes/converts the index to UTC (`tz_localize` if naive, `tz_convert` if already aware).
- Sector performance is computed, not fetched natively: `get_sector_performance` pulls 1-year daily history for 11 Sector SPDR ETFs (XLK, XLV, XLF, XLY, XLP, XLE, XLI, XLB, XLRE, XLU, XLC) and derives 1d/1w/1m/3m/YTD returns via simple ratio-of-closes math (see Math section below). `best_stock` is always `None` — yfinance has no per-sector "top stock" data.
- Economic indicators are partially synthesized from tickers: `vix` from `^VIX`, `10y_yield` from `^TNX` (divided by 10 — see below), `2y_yield` from `^IRX` (divided by 10), and `sp500_pe` is actually just the raw `^GSPC` close price (not a real P/E — a known limitation). `gdp_growth`, `cpi`, and `unemployment_rate` are always `None`, with a `logger.warning` noting they're unavailable via yfinance.
- News timestamp parsing handles both the newer nested `content` shape (`content.pubDate`, `content.provider.displayName`, `content.canonicalUrl.url`) and legacy flat shape (`publisher`, `link`) since yfinance's news payload schema has changed across versions. Sentiment is always hardcoded to `"neutral"` — yfinance provides no sentiment score.
- Earnings calendar dates from `ticker.calendar["Earnings Date"]` may be a scalar or a list; the code normalizes to a list before iterating. `eps_estimate`/`eps_actual` are always `None` for the *upcoming* calendar (yfinance doesn't provide forward estimates there); those fields are only populated by `get_earnings_history` (past quarters) via `_float_or_none`, which NaN-safely coerces `EPS Estimate`/`Reported EPS`/`Surprise(%)` cells to rounded floats.

**Usage.** Selected by `config.provider = "yfinance"`. No API key or auth required — it is the default when nothing else is configured. Notable limitations: no true `sp500_pe`, no GDP/CPI/unemployment data, no news sentiment scoring, and Yahoo Finance's unofficial API can occasionally rate-limit or change response shapes without notice (hence the defensive dual-schema news parsing).

## AlphaVantageProvider

`quantagent/tools/providers/alpha_vantage.py`

**Purpose.** Wraps the official `alpha_vantage` Python package's `TimeSeries`, `FundamentalData`, `AlphaIntelligence`, `EconIndicators`, and low-level `AlphaVantage` (for the raw `SECTOR` endpoint) clients.

**Why built this way.** Alpha Vantage is the only provider here with genuine macro/econ endpoints (real GDP, CPI, unemployment, treasury yields) and a real sector-performance endpoint, so it's the choice when those fields matter; it requires a free or paid API key.

**Auth/API key handling.** `__init__(self, api_key: str)` raises `ValueError("Alpha Vantage API key is required")` if `api_key` is falsy. The key is used to construct all five underlying Alpha Vantage client objects (`TimeSeries`, `FundamentalData`, `AlphaIntelligence`, `EconIndicators`, `AlphaVantage`) up front, once, at provider construction.

**What it overrides vs. relies on defaults for.** Implements only the 8 abstract methods — it does **not** override any of the four default methods (`get_industry_classification`, `get_earnings_history`, `get_batch_ohlcv`, `get_batch_quotes`), so batching and classification all fall through to the base class's `Semaphore(8)`-bounded per-symbol loops, and industry classification / earnings history are unavailable (base-class empty defaults).

**Data normalization details.**
- `get_ohlcv`: calls `TimeSeries.get_daily_adjusted(symbol, outputsize="full")` (full history, not just compact), then renames Alpha Vantage's numbered column scheme (`"1. open"`, `"2. high"`, `"3. low"`, `"4. close"`, `"5. adjusted close"`, `"6. volume"`) to `Open/High/Low/Close/Volume` — note both `"4. close"` and `"5. adjusted close"` map to `Close`, so whichever column survives the rename last (adjusted close, since it's processed after raw close in the `rename` dict) is what's kept. The index is parsed with `pd.to_datetime` and localized to UTC (Alpha Vantage returns naive daily dates), then the full history is truncated to the requested `period` via `_filter_by_period` (a manual dict of period-string → `timedelta`, e.g. `"1y"` → 365 days, applied as `df.index >= now - delta`) since the underlying API call always returns the full series regardless of requested period.
- `get_quote`/`get_fundamentals`/`search_symbols`: Alpha Vantage's pandas-mode responses come back as single-row DataFrames or plain dicts depending on endpoint; the code normalizes both cases (`if isinstance(data, pd.DataFrame): data = data.to_dict("records")[0]`) before extracting fields by their native key names (e.g. `"05. price"`, `"PERatio"`, `"1. symbol"`). Helper functions `_av_float`, `_av_int`, `_av_pct` defensively coerce values, treating both Python `None` and the literal string `"None"` as missing, and swallow `ValueError`/`TypeError`.
- `get_news`: uses `AlphaIntelligence.get_news_sentiment`. Publish timestamps are Alpha Vantage's compact `%Y%m%dT%H%M%S` format, parsed with `datetime.strptime` and given UTC tzinfo. Sentiment is bucketed from the raw `overall_sentiment_score` float: `> 0.25` → `"positive"`, `< -0.25` → `"negative"`, else `"neutral"`.
- `get_sector_performance`: calls the raw `SECTOR` function via the low-level `AlphaVantage._handle_api_call` client (the higher-level wrapper classes don't expose this endpoint), reads per-sector performance windows (`"1D"`, `"5D"`, `"1M"`, `"3M"`, `"YTD"`) as percentage strings (e.g. `"1.23%"`) and converts them with `_av_pct_val` (strip `%`, divide by 100, round to 4 decimals). Also surfaces a numeric `rank` per sector from the response's `rank_a` block, in addition to the standard fields.
- `get_economic_indicators`: fetches 10y/2y treasury yields via `EconIndicators.get_treasury_yield(interval="monthly", maturity=...)` and GDP/CPI/unemployment via dedicated `get_real_gdp`/`get_cpi`/`get_unemployment` calls, each returning a DataFrame whose most recent row's `"value"` column is taken. `vix` and `sp500_pe` are always `None` (Alpha Vantage has no equivalent), logged as a warning.

**Usage.** Selected by `config.provider = "alpha_vantage"`. Requires `ALPHA_VANTAGE_API_KEY` to be set (see dispatch section below). Notable limitations: free-tier Alpha Vantage has strict rate limits (historically 5 requests/minute, 25/day on the free tier), so batch operations relying on the base class's `Semaphore(8)` default can exhaust quota quickly; no industry classification or earnings-history override means those two fields are always empty for this provider.

## PolygonProvider

`quantagent/tools/providers/polygon.py`

**Purpose.** Wraps the official `polygon-api-client` (`polygon.RESTClient`) for Polygon.io market data.

**Why built this way.** Polygon offers granular intraday aggregates (down to 1-minute bars) and a real earnings-calendar endpoint with structured objects, making it the choice for intraday/short-interval work; it requires a paid or free-tier API key.

**Auth/API key handling.** `__init__(self, api_key: str)` raises `ValueError("Polygon API key is required")` if `api_key` is falsy, then constructs a single `RESTClient(api_key)` used by every method.

**What it overrides vs. relies on defaults for.** Implements only the 8 abstract methods, same as Alpha Vantage — no overrides of `get_industry_classification`, `get_earnings_history`, `get_batch_ohlcv`, or `get_batch_quotes`, so those all use the base class's defaults (industry classification and earnings history return empty; batching is per-symbol under `Semaphore(8)`).

**Data normalization details.**
- `get_ohlcv`: calls `client.get_aggs(symbol, multiplier, timespan, start, end, limit=50000)`. The `period` string (e.g. `"1y"`) is converted to a start date via `_period_to_start`'s hardcoded `timedelta` map (identical structure to Alpha Vantage's `_filter_by_period` map — `"1d"` through `"10y"`, defaulting to 365 days for unrecognized periods). The `interval` string (e.g. `"1d"`, `"5m"`, `"1h"`) is split into a Polygon `(multiplier, timespan)` pair via two lookup dicts, `_interval_to_timespan` (mapping to `"minute"/"hour"/"day"/"week"/"month"`) and `_interval_multiplier` (extracting the numeric multiplier, e.g. `"5m"` → `(5, "minute")`, `"1h"`/`"60m"` → `(1, "hour")`), both defaulting to `(1, "day")` for unknown intervals. Each returned `Agg` object's millisecond `timestamp` is converted to a UTC `datetime` (`fromtimestamp(ts / 1000, tz=UTC)`) and rows are assembled into a DataFrame indexed by `Date`, sorted ascending.
- `get_quote`: Polygon's last-quote object may expose `last_price` or only `ask_price`/`bid_price` depending on tier/endpoint; the code uses `hasattr` guards to avoid `AttributeError`. `change`/`change_percent`/`volume` are always `None` — Polygon's last-quote endpoint doesn't return them.
- `get_fundamentals`: Polygon has no fundamentals endpoint, so every standard fundamental field (P/E, P/B, EV/EBITDA, ROE, ROA, debt/equity, FCF, dividend yield, EPS, growth, beta) is hardcoded `None`. Instead, `get_ticker_details` supplies extra non-standard fields bolted onto the same dict: `market_cap`, `shares_outstanding`, `employees`, and `sector` (from SIC description) — present in the returned dict but not part of the abstract contract's documented fields.
- `get_news`: uses `list_ticker_news`; `_parse_news_timestamp` handles Polygon's `published_utc` attribute, which may already be a `datetime` or an ISO string with a trailing `Z` (converted via `fromisoformat` after replacing `Z` with `+00:00`). Sentiment is always hardcoded `"neutral"` (Polygon news objects carry no sentiment score in this integration).
- `get_earnings_calendar`: reads `report_date` or falls back to `calendar_date` from each earnings object, parses via `fromisoformat`.
- `get_sector_performance`: same 11-ETF Sector SPDR approach as `YFinanceProvider` (identical ticker map, duplicated as `_POLYGON_SECTOR_ETFS`), fetching 1 year of daily aggregates per ETF via `_fetch_sector_etf_history` and computing 1d/1w/1m/3m/YTD returns with the same ratio-of-closes formulas. Failures per-ETF are caught and logged, not propagated (`get_sector_performance` simply omits that sector).
- `get_economic_indicators`: Polygon has no macro/econ data at all; every field is `None` and a single `logger.warning` notes the limitation.

**Usage.** Selected by `config.provider = "polygon"`. Requires `POLYGON_API_KEY` (see dispatch section below). Notable limitations: no fundamentals data (P/E, P/B, etc. are always `None`; only market cap/shares/employees/sector are available as bonus fields), no economic indicators, and quote data is missing volume/change fields the other two providers supply.

## Provider selection (get_active_provider)

`quantagent/tools/providers/__init__.py` exposes `get_active_provider(config: QuantAgentConfig) -> AbstractDataProvider`, the single factory function every caller (the TUI's cached `get_provider()`, `tools_registry.py`'s tool binding, tests) uses to construct a provider — concrete provider classes are never instantiated directly outside this module and tests.

**Dispatch logic.** A `match config.provider:` statement selects the concrete class:

| `config.provider` value | Class constructed | API key required |
|---|---|---|
| `"yfinance"` | `YFinanceProvider()` | none |
| `"alpha_vantage"` | `AlphaVantageProvider(api_key=...)` | `ALPHA_VANTAGE_API_KEY` |
| `"polygon"` | `PolygonProvider(api_key=...)` | `POLYGON_API_KEY` |
| anything else | — | raises `ValueError(f"Unknown provider: {config.provider}")` |

**API key resolution (`_get_api_key(prefix)`).** For the two key-requiring providers, the key is resolved as follows:
1. If `~/.quantagent/.env` exists, it is loaded via `dotenv.load_dotenv(dotenv_path=env_path, override=False)` — `override=False` means any key already present in the process environment (e.g. exported in the shell) takes precedence over the `.env` file.
2. The key is then read from `os.environ.get(f"{prefix}_API_KEY", "")` (e.g. `ALPHA_VANTAGE_API_KEY`, `POLYGON_API_KEY`).
3. **Missing API keys.** If the environment variable is absent or empty, `_get_api_key` logs a warning (`"%s_API_KEY not found in environment"`) and returns `""`. That empty string is then passed into the provider's `__init__`, which is where the actual failure happens: both `AlphaVantageProvider.__init__` and `PolygonProvider.__init__` raise `ValueError` immediately if `api_key` is falsy (`"Alpha Vantage API key is required"` / `"Polygon API key is required"`). So a missing key surfaces as a logged warning followed by a hard `ValueError` at provider construction time, not a silent no-op or a deferred per-request failure — `get_active_provider` fails fast, before any tool call is attempted.

## Math: normalization, batching, and rate-limit formulas

**OHLCV normalization to the standard shape.** Every provider ends its `get_ohlcv`/`get_batch_ohlcv` path with the same target shape: a `pd.DataFrame` with exactly the columns `Open, High, Low, Close, Volume` (extras dropped, in that order where applicable) and a UTC-tz-aware `DatetimeIndex`. Each provider gets there differently:
- yfinance: `tz_convert(UTC)` (source index already tz-aware in local exchange time) for single-symbol; for batch, `tz_localize(UTC) if index.tz is None else tz_convert(UTC)` since `yf.download`'s combined frame's tz-awareness varies.
- Alpha Vantage: `pd.to_datetime` (naive) then `tz_localize(UTC)` — the API returns naive daily date strings.
- Polygon: constructed directly from `datetime.fromtimestamp(agg.timestamp / 1000, tz=UTC)` — Polygon's `timestamp` field is Unix milliseconds, so it is always built UTC-aware from the start, no localization step needed.

**Bounded batch concurrency.** The base class's `get_batch_ohlcv`/`get_batch_quotes` defaults use `asyncio.Semaphore(_BATCH_CONCURRENCY)` where `_BATCH_CONCURRENCY = 8`. Each per-symbol fetch is wrapped:
```python
async def _fetch(sym):
    async with semaphore:
        try:
            results[sym] = await self.get_ohlcv(sym, ...)
        except Exception as exc:
            logger.warning(...)
```
and all symbols are scheduled via `asyncio.TaskGroup`, so at most 8 requests are in flight concurrently regardless of how many symbols are requested — this is the mechanism that keeps a 500-symbol universe scan from exceeding a provider's per-second/per-minute rate limit while still overlapping network latency (as opposed to a fully serial loop, which would take `N × latency` wall-clock time). Only `YFinanceProvider` overrides this (with `yf.download`'s own internal `threads=True` batching) — Alpha Vantage and Polygon both rely on the base-class semaphore-bounded default.

**Period-to-date-range conversion.** Alpha Vantage's `_filter_by_period` and Polygon's `_period_to_start` both use an equivalent hardcoded map from period string to `timedelta` (`"1d"`→1 day, `"5d"`→5 days, `"1mo"`→30 days, `"3mo"`→90 days, `"6mo"`→180 days, `"1y"`→365 days, `"2y"`→730 days, `"5y"`→1825 days, `"10y"`→3650 days), applied as `start = now - delta` (Polygon fetches only that range from the API; Alpha Vantage fetches the full history and then filters `df.index >= now - delta` client-side, since its daily-adjusted endpoint has no server-side range parameter beyond compact/full).

**Sector performance return math.** Both `YFinanceProvider` and `PolygonProvider` compute sector ETF performance identically:
- `_pct_change(series, periods)` / `_pct(series, periods)`: `close.iloc[-1] / close.iloc[-(periods+1)] - 1`, i.e. simple (not log) return over `periods` trading bars — 1 for 1-day, 5 for 1-week, 21 for 1-month, 63 for 3-months (approximate trading-day counts).
- `_ytd_return` / `_ytd`: filters the close series to `index >= datetime(now.year, 1, 1, tzinfo=UTC)` and computes `last / first - 1` over that filtered slice; requires at least 2 data points, else returns `None` (yfinance) or `0.0` (Polygon — a minor inconsistency between the two implementations).

**Percentage-string parsing.** Alpha Vantage returns several fields as percentage strings rather than floats (e.g. sector performance `"1.23%"`, quote `"10. change percent"`). `_av_pct_val` and `_av_pct` both strip the trailing `%` and, for `_av_pct_val` only, divide by 100 to get a decimal fraction (sector performance is stored as a fraction like `0.0123`; quote change-percent is stored as the raw percentage number like `1.23`) — callers of `get_quote` vs `get_sector_performance` on Alpha Vantage should be aware these two "percent" fields are on different scales.

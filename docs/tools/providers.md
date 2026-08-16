# Data Providers

`quantagent/tools/providers/`

The data-source abstraction layer that sits between QuantAgent's analysis tools and the actual market data APIs (yfinance, Alpha Vantage, Polygon). This layer lets you switch data providers without changing any analysis code.

---

## Why Providers Exist

Every analysis tool needs market data — prices, fundamentals, news, etc. But different data providers have different APIs, different data formats, and different rate limits. If every tool had to know about each provider's quirks, the code would be a mess.

The provider abstraction solves this by:
1. **Defining a standard interface** — all providers implement the same methods
2. **Normalizing data** — all providers return data in the same format
3. **Handling provider-specific logic** — each provider handles its own API quirks internally

This means the rest of the codebase just calls `provider.get_ohlcv("AAPL")` and gets back a standard DataFrame, regardless of whether the data came from yfinance, Alpha Vantage, or Polygon.

---

## The AbstractDataProvider Interface

All providers implement this interface. It defines 8 required methods and 4 optional methods.

### Required Methods

Every provider must implement these:

| Method | What it does | Returns |
|--------|--------------|---------|
| `get_ohlcv` | Fetch price history | DataFrame with Open/High/Low/Close/Volume columns, UTC DatetimeIndex |
| `get_quote` | Fetch current quote | Dict with price, change_pct, volume, market_cap, etc. |
| `get_fundamentals` | Fetch fundamental data | Dict with P/E, P/B, ROE, ROA, debt/equity, etc. |
| `search_symbols` | Search for symbols by name | List of dicts with symbol, name, exchange |
| `get_news` | Fetch recent news | List of dicts with title, source, url, published_at, sentiment |
| `get_earnings_calendar` | Fetch upcoming earnings | List of dicts with date, eps_estimate, eps_actual, quarter |
| `get_sector_performance` | Fetch sector returns | Dict with sector returns by timeframe |
| `get_economic_indicators` | Fetch macro data | Dict with vix, yields, sp500_pe, gdp_growth, cpi, unemployment |

### Optional Methods (with defaults)

These have default implementations, but providers can override them for better performance:

| Method | Default behavior | Why override |
|--------|------------------|--------------|
| `get_industry_classification` | Returns None for sector/industry | Override if provider has classification data |
| `get_earnings_history` | Returns empty list | Override if provider has historical earnings |
| `get_batch_ohlcv` | Loops through symbols one-by-one | Override with native batch API for speed |
| `get_batch_quotes` | Loops through symbols one-by-one | Override with native batch API for speed |

**Batch methods use bounded concurrency** — the default implementations fetch up to 8 symbols at once to avoid overwhelming the provider's rate limits.

---

## Available Providers

### YFinanceProvider

**Default provider** — free, no API key required.

| Aspect | Details |
|--------|---------|
| **Source** | Yahoo Finance via `yfinance` library |
| **API key** | Not required |
| **Best for** | General use, getting started, testing |
| **Limitations** | No real P/E ratio, no GDP/CPI/unemployment, no news sentiment, occasional rate limits |

**What it does well:**
- Covers all 8 required methods
- Overrides batch OHLCV with efficient `yf.download()` call
- Provides industry classification and earnings history
- No setup required — just works

**What it doesn't do well:**
- `sp500_pe` is actually just the S&P 500 price (not a real P/E ratio)
- No macroeconomic data (GDP, CPI, unemployment)
- News sentiment is always "neutral" (yfinance doesn't provide sentiment)
- Sector performance is computed from 11 sector ETFs (not native data)

### AlphaVantageProvider

**Premium provider** — requires API key (free tier available).

| Aspect | Details |
|--------|---------|
| **Source** | Alpha Vantage API |
| **API key** | Required (`ALPHA_VANTAGE_API_KEY`) |
| **Best for** | When you need real macroeconomic data |
| **Limitations** | Strict rate limits (5 req/min, 25/day on free tier), no industry classification, no earnings history |

**What it does well:**
- Real macroeconomic data (GDP, CPI, unemployment, treasury yields)
- Real sector performance data (not computed from ETFs)
- News sentiment scoring
- Covers all 8 required methods

**What it doesn't do well:**
- Free tier has very strict rate limits
- No industry classification (returns None)
- No earnings history (returns empty list)
- Batch operations use default loop (no native batch API)

### PolygonProvider

**Premium provider** — requires API key (free tier available).

| Aspect | Details |
|--------|---------|
| **Source** | Polygon.io API |
| **API key** | Required (`POLYGON_API_KEY`) |
| **Best for** | Intraday data, granular timeframes |
| **Limitations** | No fundamentals, no economic indicators, limited quote data |

**What it does well:**
- Granular intraday data (down to 1-minute bars)
- Real earnings calendar with structured data
- Covers all 8 required methods

**What it doesn't do well:**
- No fundamental data (P/E, ROE, etc. all return None)
- No economic indicators (all return None)
- Quote data missing volume/change fields
- No industry classification or earnings history

---

## Provider Selection

The active provider is selected via `config.provider` in your configuration:

```python
config.provider = "yfinance"  # or "alpha_vantage" or "polygon"
```

The `get_active_provider()` factory function constructs the appropriate provider:

| Config value | Provider class | API key required |
|--------------|----------------|------------------|
| `"yfinance"` | `YFinanceProvider()` | None |
| `"alpha_vantage"` | `AlphaVantageProvider(api_key)` | `ALPHA_VANTAGE_API_KEY` |
| `"polygon"` | `PolygonProvider(api_key)` | `POLYGON_API_KEY` |

### API Key Resolution

For providers that require API keys, the key is resolved in this order:

1. **Environment variable** — e.g. `ALPHA_VANTAGE_API_KEY`
2. **`.env` file** — `~/.quantagent/.env` is loaded if it exists
3. **Fail fast** — if the key is missing, provider construction raises `ValueError`

This ensures you get a clear error message at startup rather than mysterious failures later.

---

## Data Normalization

All providers normalize their data to the same format, so the rest of the codebase doesn't need to know which provider is active.

### OHLCV Data

All providers return DataFrames with:
- **Columns:** `Open`, `High`, `Low`, `Close`, `Volume` (in that order)
- **Index:** UTC timezone-aware DatetimeIndex
- **Sorting:** Ascending by date (oldest first)

Each provider gets there differently:
- **yfinance:** Converts from exchange-local timezone to UTC
- **Alpha Vantage:** Parses naive dates and localizes to UTC
- **Polygon:** Constructs UTC timestamps directly from Unix milliseconds

### Batch Operations

The default batch implementations use bounded concurrency:

```python
async def get_batch_ohlcv(self, symbols, period="1y", interval="1d"):
    semaphore = asyncio.Semaphore(8)  # max 8 concurrent requests
    
    async def _fetch(sym):
        async with semaphore:
            return await self.get_ohlcv(sym, period, interval)
    
    results = await asyncio.gather(*[_fetch(sym) for sym in symbols])
    return dict(zip(symbols, results))
```

This prevents overwhelming the provider's rate limits while still parallelizing I/O-bound network requests.

**yfinance overrides this** with a native batch download that's more efficient.

---

## Period-to-Date-Range Conversion

All providers convert period strings (like "1y", "6mo") to date ranges:

| Period | Days |
|--------|------|
| `1d` | 1 |
| `5d` | 5 |
| `1mo` | 30 |
| `3mo` | 90 |
| `6mo` | 180 |
| `1y` | 365 |
| `2y` | 730 |
| `5y` | 1825 |
| `10y` | 3650 |

**Alpha Vantage** fetches the full history then filters client-side (its API doesn't support server-side filtering).

**Polygon** fetches only the requested range from the API.

---

## Sector Performance

Both yfinance and Polygon compute sector performance from 11 sector ETFs:

| Sector | ETF |
|--------|-----|
| Technology | XLK |
| Healthcare | XLV |
| Financials | XLF |
| Consumer Discretionary | XLY |
| Consumer Staples | XLP |
| Energy | XLE |
| Industrials | XLI |
| Materials | XLB |
| Real Estate | XLRE |
| Utilities | XLU |
| Communication Services | XLC |

Returns are computed as simple percentage changes over 1-day, 1-week, 1-month, 3-month, and YTD periods.

**Alpha Vantage** is the only provider with native sector performance data.

---

## Summary

The provider abstraction layer lets QuantAgent work with multiple data sources without changing analysis code:

- **AbstractDataProvider** — standard interface all providers implement
- **YFinanceProvider** — free, no API key, good for getting started
- **AlphaVantageProvider** — real macro data, requires API key, strict rate limits
- **PolygonProvider** — granular intraday data, requires API key, no fundamentals

All providers normalize data to the same format:
- OHLCV DataFrames with UTC DatetimeIndex
- Standardized quote/fundamental/news dictionaries
- Bounded concurrency for batch operations

Use yfinance for general use and testing. Use Alpha Vantage when you need real macroeconomic data. Use Polygon when you need granular intraday data.

Remember: providers are swappable — you can change `config.provider` and all your analysis code keeps working. That's the power of abstraction.

# Market Data Tools

`quantagent/tools/market_data.py`

A thin async pass-through layer that fetches raw market data from your data provider. Think of it as a universal remote control for your data source — it sends commands to your provider (yfinance, Alpha Vantage, Polygon, etc.) and returns whatever the provider sends back.

This module doesn't do any analysis or calculations. It just fetches data. All the heavy lifting — computing indicators, screening stocks, analyzing sectors — happens in other modules that use these functions as building blocks.

---

## Why This Module Exists

Every tool in QuantAgent needs market data, but different tools need different kinds of data. Some need price history, some need company fundamentals, some need sector performance data. Rather than having each tool figure out how to talk to the data provider, they all use these standardized functions.

This gives us three big benefits:

1. **One place to normalize data** — every function upper-cases ticker symbols and returns data in a consistent format, so downstream tools don't need to worry about case sensitivity or data shape differences between providers.

2. **Provider-agnostic code** — the rest of the codebase doesn't care if you're using yfinance, Alpha Vantage, or Polygon. They just call `get_ohlcv()` and get back a DataFrame. If you switch providers, only this module changes.

3. **Workflow-friendly** — because every function takes `provider: AbstractDataProvider` as its first argument, they can all be used as workflow steps. This lets you chain data fetches together in custom workflows.

---

## get_ohlcv

**Agent tool:** `get_ohlcv_data`

Fetches historical price data (Open, High, Low, Close, Volume) for a single stock over a specified time period.

### What It Does

Downloads a time series of price bars for a stock. Each bar represents one time period (daily, weekly, monthly, etc.) and contains five values:

- **Open** — the price at the start of the period
- **High** — the highest price during the period
- **Low** — the lowest price during the period
- **Close** — the price at the end of the period
- **Volume** — how many shares traded during the period

This is the raw material for all technical analysis. Every indicator (moving averages, RSI, MACD, Bollinger Bands, etc.) is computed from these five columns.

### How It Works

1. **Normalize the symbol** — converts the ticker to uppercase (so "aapl" becomes "AAPL")
2. **Call the provider** — asks your data provider for the requested period and interval
3. **Return the data** — gives back a pandas DataFrame with the price history

That's it. No caching, no validation, no computation. Just a clean pass-through.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider (yfinance, Alpha Vantage, etc.) |
| `symbol` | `str` | required | Stock ticker (e.g. "AAPL", "MSFT") |
| `period` | `str` | `"1y"` | How far back to look (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y) |
| `interval` | `str` | `"1d"` | Bar size (1m, 5m, 15m, 30m, 60m, 1d, 1wk, 1mo) |

### Returns

A pandas DataFrame with:
- **Index:** DatetimeIndex (UTC timezone)
- **Columns:** Open, High, Low, Close, Volume

### Usage

**Python API:**
```python
df = await get_ohlcv(provider, "AAPL", period="1y", interval="1d")
```

**Agent tool:** The agent tool wrapper calls this function and returns a JSON summary (bar count, latest close/volume, date range) instead of the raw DataFrame, since sending a full year of daily data to the LLM would be wasteful.

### Design Notes

**Why not cache this?** Price data changes constantly (every minute during market hours), so caching would either serve stale data or require frequent invalidation. Other modules that need price data (like the screener or technical indicators) handle their own caching strategies based on their specific needs.

**Why upper-case the symbol?** Different providers have different case sensitivity rules. By normalizing here, we ensure consistent behavior regardless of whether the user types "aapl", "AAPL", or "Aapl".

---

## get_quote

**Agent tool:** `get_stock_quote`

Fetches the current/latest quote for a stock.

### What It Does

Gets a snapshot of a stock's current trading data — typically the latest price, daily change, volume, and market cap. The exact fields depend on your data provider.

### How It Works

1. **Normalize the symbol** — converts to uppercase
2. **Call the provider** — asks for the latest quote
3. **Return the data** — gives back a dictionary with quote fields

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `symbol` | `str` | required | Stock ticker |

### Returns

A dictionary with provider-dependent fields. Typical fields include:
- `price` — current/latest price
- `change` — daily price change
- `change_percent` — daily percentage change
- `volume` — trading volume
- `market_cap` — total market value
- `bid`, `ask` — bid/ask prices (if available)

### Usage

**Python API:**
```python
quote = await get_quote(provider, "AAPL")
```

**Agent tool:** Returns the quote as JSON.

---

## get_fundamentals

**Agent tool:** `get_stock_fundamentals`

Fetches fundamental company data — financial ratios, metrics, and metadata.

### What It Does

Gets a company's financial health metrics — things like P/E ratio, return on equity, debt levels, revenue growth, and dividend yield. This data comes from the company's financial statements (balance sheet, income statement, cash flow statement).

Fundamental data is essential for value investing, quality screening, and financial health checks. It tells you whether a company is cheap or expensive, profitable or losing money, heavily indebted or financially stable.

### How It Works

1. **Normalize the symbol** — converts to uppercase
2. **Call the provider** — asks for fundamental data
3. **Return the data** — gives back a dictionary with financial metrics

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `symbol` | `str` | required | Stock ticker |

### Returns

A dictionary with provider-dependent fields. Typical fields include:
- **Valuation:** `pe_ratio`, `pb_ratio`, `ev_ebitda`
- **Profitability:** `roe`, `roa`, `gross_margin`, `net_margin`
- **Leverage:** `debt_equity`, `current_ratio`
- **Growth:** `revenue_growth`, `eps_growth`
- **Income:** `eps`, `dividend_yield`
- **Size:** `market_cap`, `beta`

### Usage

**Python API:**
```python
fundamentals = await get_fundamentals(provider, "AAPL")
```

**Agent tool:** Returns the fundamentals as JSON.

### Where It's Used

This function is called by:
- **Fundamental screener** — filters stocks by financial metrics
- **Peer comparison** — compares fundamentals across multiple stocks
- **DCF valuation** — uses financial data to estimate intrinsic value
- **Piotroski/Altman scoring** — computes financial health scores
- **Stock research workflow** — includes fundamentals in the research report

---

## get_earnings_calendar

**Agent tool:** `get_earnings_calendar`

Fetches upcoming earnings dates for a single stock.

### What It Does

Gets a list of future dates when the company is scheduled to report earnings. Earnings announcements are major market events — they can cause big price moves and often drive trading decisions.

### How It Works

1. **Normalize the symbol** — converts to uppercase
2. **Call the provider** — asks for upcoming earnings within the lookahead window
3. **Return the data** — gives back a list of earnings events

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `symbol` | `str` | required | Stock ticker |
| `lookahead_days` | `int` | `90` | How far ahead to search (in days) |

### Returns

A list of dictionaries, each representing an earnings event. Typical fields:
- `date` — earnings announcement date
- `eps_estimate` — analyst consensus EPS estimate
- `quarter` — which fiscal quarter (e.g. "Q1 2026")

### Usage

**Python API:**
```python
events = await get_earnings_calendar(provider, "AAPL", lookahead_days=90)
```

**Agent tool:** Returns the earnings calendar as JSON.

### Design Notes

**Why separate from `get_earnings_calendar_range`?** This function is for single-stock lookups — fast and simple. The range version (in `event_analysis.py`) handles multiple stocks with caching and concurrency, which is more complex. Keeping them separate lets each optimize for its use case.

---

## get_news

**Agent tool:** `get_stock_news`

Fetches recent news headlines for a stock.

### What It Does

Gets a list of recent news articles related to a stock. News can drive price movements, provide context for technical patterns, and help you understand why a stock is moving.

### How It Works

1. **Normalize the symbol** — converts to uppercase
2. **Call the provider** — asks for news within the lookback window
3. **Return the data** — gives back a list of news items

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `symbol` | `str` | required | Stock ticker |
| `days` | `int` | `7` | How far back to look (in days) |

### Returns

A list of dictionaries, each representing a news item. Typical fields:
- `title` — headline
- `source` — news source (e.g. "Bloomberg", "Reuters")
- `url` — link to full article
- `published_at` — publication timestamp
- `sentiment` — sentiment score (if available from provider)

### Usage

**Python API:**
```python
headlines = await get_news(provider, "AAPL", days=7)
```

**Agent tool:** Returns the news as JSON.

### Where It's Used

This function is the final step in the `stock_research` workflow, providing qualitative context after the quantitative analysis.

---

## search_symbols

**Agent tool:** `search_stock_symbols`

Looks up ticker symbols by company name or partial query.

### What It Does

Helps you find the right ticker symbol when you know the company name but not the exact ticker. For example, searching "apple" returns "AAPL", searching "microsoft" returns "MSFT".

### How It Works

1. **Call the provider** — asks for symbol matches (no normalization needed since this is free-text search)
2. **Return the data** — gives back a list of candidate matches

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `query` | `str` | required | Company name or partial ticker |

### Returns

A list of dictionaries, each representing a match. Typical fields:
- `symbol` — ticker symbol
- `name` — company name
- `exchange` — stock exchange

### Usage

**Python API:**
```python
matches = await search_symbols(provider, "apple")
```

**Agent tool:** Returns the matches as JSON.

### Design Notes

**Why no upper-casing?** This is the only function in the module that doesn't upper-case its input. The query is free text (a company name or partial ticker), not a known symbol, so normalization is left to the provider's search logic.

---

## get_sector_performance

**Agent tool:** `get_sector_performance`

Fetches performance data across all major market sectors.

### What It Does

Gets a snapshot of how different market sectors are performing — typically 1-day, 1-week, 1-month, 3-month, and year-to-date returns for each sector. This helps you see which parts of the market are leading and which are lagging.

### How It Works

1. **Call the provider** — asks for sector performance data
2. **Return the data** — gives back a dictionary keyed by sector

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |

### Returns

A dictionary keyed by sector name, with performance figures for each timeframe. Example structure:
```json
{
  "Technology": {"1d": 0.012, "1w": 0.034, "1m": 0.056, "3m": 0.112, "ytd": 0.234},
  "Healthcare": {"1d": -0.005, "1w": 0.012, "1m": 0.023, "3m": 0.067, "ytd": 0.145},
  ...
}
```

### Usage

**Python API:**
```python
sectors = await get_sector_performance(provider)
```

**Agent tool:** Returns the sector performance as JSON.

### Design Notes

**Why not rank the sectors?** This function returns raw, unranked data straight from the provider. If you want ranked sectors (e.g. "Technology is #1, Healthcare is #2"), use `get_sector_performance_ranked` in `sector_analysis.py`, which adds multi-timeframe ranking logic.

---

## get_economic_indicators

**Agent tool:** `get_economic_indicators`

Fetches macroeconomic indicators — VIX, treasury yields, P/E ratios, GDP, etc.

### What It Does

Gets a snapshot of the broader economic environment — market volatility (VIX), interest rates (treasury yields), valuation levels (S&P 500 P/E), and economic health metrics (GDP growth, CPI, unemployment). These indicators help you understand the macro context for your investment decisions.

### How It Works

1. **Call the provider** — asks for economic indicator data
2. **Return the data** — gives back a dictionary with indicator values

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |

### Returns

A dictionary mapping indicator names to values. Typical fields:
- `vix` — CBOE Volatility Index (market fear gauge)
- `10y_yield` — 10-year Treasury yield
- `2y_yield` — 2-year Treasury yield
- `sp500_pe` — S&P 500 P/E ratio
- `gdp_growth` — GDP growth rate
- `cpi` — Consumer Price Index (inflation)
- `unemployment_rate` — unemployment rate

Fields unavailable from your provider are returned as `null` rather than raising an error, so you always get a consistent dictionary shape.

### Usage

**Python API:**
```python
indicators = await get_economic_indicators(provider)
```

**Agent tool:** Returns the indicators as JSON.

### Design Notes

**Why return nulls instead of raising?** Different providers have different coverage. yfinance doesn't have GDP or CPI data. Alpha Vantage doesn't have VIX. By returning nulls for missing fields, the function provides a stable interface regardless of which provider you're using. The caller can check for nulls and handle them appropriately.

---

## Summary

Every function in this module follows the same pattern:

1. **Normalize inputs** — upper-case ticker symbols (except `search_symbols`)
2. **Call the provider** — forward to the corresponding method on `AbstractDataProvider`
3. **Return the result** — give back whatever the provider returns, untouched

None of these functions perform validation, retries, caching, or computation. Those concerns live elsewhere:
- **Validation and retries** — handled by the provider implementations
- **Caching** — handled by `cache.py` (used by other modules, not this one)
- **Computation** — handled by the higher-level tools that consume this data

This keeps the module simple, predictable, and easy to test. It's just a thin layer between the rest of QuantAgent and your data source.

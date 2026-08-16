# Market Overview Tools

`quantagent/tools/market_overview.py`

Market-wide dashboards that give you a bird's-eye view of what's happening in the stock market. These tools answer questions like:
- What are the major indices doing?
- Which stocks are moving the most?
- What's the overall market regime?
- What's the sentiment?

The module mixes two speed tiers:
- **Fast path** — uses only index ETFs and a handful of tickers, completes in seconds
- **Deep path** — analyzes hundreds of stocks, requires a cache warm-up on first use

---

## get_market_summary

**Agent tool:** `get_market_summary`

A one-shot snapshot of the entire market — indices, timing signals, breadth, sentiment, regime, and key support/resistance levels.

### What It Does

Rolls up multiple market analyses into a single comprehensive report:
- **Index prices and trends** — SPY, QQQ, DIA, IWM
- **Market timing** — distribution days, follow-through day status
- **Breadth** — % of stocks above moving averages
- **Sentiment** — fear & greed score
- **Regime** — composite market regime with exposure guidance
- **Key levels** — SPY support and resistance

### How It Works

1. **Fetch index data** — downloads price data for 4 major index ETFs (SPY, QQQ, DIA, IWM)
2. **Compute timing signals** — distribution days and follow-through day for SPY
3. **Compute breadth** — % of sector ETFs above their moving averages
4. **Compute sentiment** — fear & greed score
5. **Detect regime** — composite market regime score
6. **Find key levels** — support and resistance for SPY
7. **Assemble report** — package everything into a single dictionary

All sub-analyses run concurrently for speed. The whole summary completes in seconds.

### Parameters

| Name | Type | Description |
|------|------|-------------|
| `provider` | `AbstractDataProvider` | Your data provider |

### Returns

A dictionary with:
```json
{
  "as_of": "2026-08-15",
  "indices": {
    "SPY": {"name": "S&P 500", "price": 512.3, "change_1d": 0.0042, "trend": "up"},
    "QQQ": {"name": "Nasdaq 100", "price": 445.1, "change_1d": 0.0068, "trend": "up"},
    "DIA": {"name": "Dow Jones", "price": 38950.2, "change_1d": 0.0031, "trend": "up"},
    "IWM": {"name": "Russell 2000", "price": 198.5, "change_1d": -0.0015, "trend": "mixed"}
  },
  "timing": {
    "distribution_days": 2,
    "follow_through": {"status": "confirmed-uptrend", "ftd_date": "2026-08-10"}
  },
  "breadth": {"universe": "sector_etfs", "pct_above": {"20": 72.7, "50": 63.6, "200": 81.8}},
  "sentiment": {"score": 34.2, "label": "greed"},
  "regime": {"regime": "bull", "score": 68.2, "confidence": 0.78},
  "recommended_exposure": {"min_pct": 70, "max_pct": 90, "label": "healthy"},
  "key_levels": {"support": [505.0, 500.0], "resistance": [520.0, 525.0], "current_price": 512.3}
}
```

### Usage

**Python API:**
```python
summary = await get_market_summary(provider)
```

**Agent tool:**
```
get_market_summary()
```

---

## get_top_movers

**Agent tool:** `get_top_movers`

Returns the top gainers or losers in a universe over a chosen time window.

### What It Does

Finds the stocks with the biggest price moves — either up (gainers) or down (losers) — over 1 day, 1 week, or 1 month.

### How It Works

1. **Load universe data** — fetches price data for all stocks in the universe from the BreadthStore cache
2. **Compute returns** — calculates percentage change over the chosen window
3. **Rank and filter** — sorts by return (descending for gainers, ascending for losers) and takes the top N

**Deep path:** This tool requires the BreadthStore cache to be warm. If it's cold, the first call will be slow (minutes for a full universe), but subsequent calls will be fast.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `universe` | `str` | `"sp500"` | Universe to analyze (sp500, nasdaq100, sector_etfs) |
| `direction` | `str` | `"up"` | "up" for gainers, "down" for losers |
| `count` | `int` | `10` | Number of results |
| `period` | `str` | `"1d"` | Time window (1d, 1w, 1m) |

### Returns

A DataFrame with columns:
- `symbol` — stock ticker
- `price` — current price
- `change_pct` — percentage change over the period
- `volume` — latest volume
- `avg_volume_20d` — 20-day average volume

### Usage

**Python API:**
```python
df = await get_top_movers(provider, universe="sp500", direction="up", count=10, period="1d")
```

**Agent tool:**
```
get_top_movers(universe="sp500", direction="up", count=10, period="1d")
```

---

## get_most_active

**Agent tool:** `get_most_active`

Returns the stocks with the highest relative volume — today's volume compared to the 20-day average.

### What It Does

Finds stocks with unusual volume activity. A stock trading at 3x its normal volume is getting attention — maybe there's news, a breakout, or institutional buying/selling.

### How It Works

1. **Load universe data** — fetches price and volume data from the BreadthStore cache
2. **Compute volume ratio** — today's volume / 20-day average volume
3. **Rank** — sorts by volume ratio (highest first) and takes the top N

**Why volume ratio, not raw volume?** Raw volume is dominated by mega-cap stocks (AAPL, MSFT) that always trade millions of shares. Volume ratio surfaces stocks with *unusual* activity relative to their normal pattern — much more useful for spotting catalysts.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `universe` | `str` | `"sp500"` | Universe to analyze |
| `count` | `int` | `10` | Number of results |

### Returns

A DataFrame with columns:
- `symbol` — stock ticker
- `price` — current price
- `volume_ratio` — today's volume / 20-day average
- `volume` — today's volume
- `avg_volume_20d` — 20-day average volume

### Usage

**Python API:**
```python
df = await get_most_active(provider, universe="sp500", count=10)
```

**Agent tool:**
```
get_most_active(universe="sp500", count=10)
```

---

## generate_market_heatmap

**Agent tool:** `generate_market_heatmap`

Creates a hierarchical heatmap of a chosen metric across a universe, grouped by sector and industry.

### What It Does

Generates the data behind a Finviz-style market heatmap — a tree structure where each stock is a "tile" sized by market cap (actually dollar volume, since market cap isn't stored) and colored by a chosen metric (performance, volatility, volume, or RSI).

### How It Works

1. **Load universe data** — fetches price and volume data from the BreadthStore cache
2. **Classify stocks** — assigns each stock to a sector and industry
3. **Compute metric** — calculates the chosen metric for each stock
4. **Build tree** — organizes stocks into a nested structure: sector → industry → symbol
5. **Summarize** — for the agent, flattens the tree and computes per-group summaries

**Deep path:** Like the other universe-scale tools, this requires the BreadthStore cache.

### Available Metrics

| Metric | What it measures |
|--------|------------------|
| `performance` | 1-day return |
| `volatility` | 21-day annualized volatility |
| `volume` | Volume ratio (today / 20-day avg) |
| `rsi` | 14-day RSI |

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `universe` | `str` | `"sp500"` | Universe to analyze (sp500 or nasdaq100) |
| `metric` | `str` | `"performance"` | Metric to display |
| `group_by` | `str` | `"sector"` | Grouping level (sector or industry) |

### Returns

**Raw function:** A nested dictionary:
```json
{
  "metric": "performance",
  "group_by": "sector",
  "as_of": "2026-08-15",
  "groups": {
    "Technology": {
      "Semiconductors": {
        "NVDA": {"value": 0.0287, "size": 12500000000},
        "AMD": {"value": 0.0156, "size": 4200000000}
      },
      "Software": {
        "MSFT": {"value": 0.0122, "size": 18500000000},
        ...
      }
    },
    ...
  }
}
```

**Agent tool:** A flattened summary:
```json
{
  "metric": "performance",
  "group_by": "sector",
  "groups": {
    "Technology": {
      "n_symbols": 78,
      "mean_value": 0.0134,
      "largest": [
        {"symbol": "AAPL", "value": 0.0091},
        {"symbol": "MSFT", "value": 0.0122},
        {"symbol": "NVDA", "value": 0.0287}
      ]
    },
    ...
  }
}
```

### Usage

**Python API:**
```python
heatmap = await generate_market_heatmap(provider, universe="sp500", metric="performance", group_by="sector")
```

**Agent tool:**
```
generate_market_heatmap(universe="sp500", metric="performance", group_by="sector")
```

---

## Summary

These market overview tools give you a comprehensive view of the market:

- **get_market_summary** — one-shot market snapshot (indices, timing, breadth, sentiment, regime)
- **get_top_movers** — biggest gainers and losers
- **get_most_active** — stocks with unusual volume
- **generate_market_heatmap** — hierarchical heatmap of any metric

Use these tools to get a quick pulse on the market. The market summary is especially useful as a daily check-in — it tells you everything you need to know about the current market environment in one call.

Remember: the deep-path tools (top movers, most active, heatmap) require the BreadthStore cache. The first call will be slow, but subsequent calls will be fast. If you need speed and don't need universe-scale analysis, stick with the fast-path tools like `get_market_summary`.

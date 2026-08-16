# Sector Analysis Tools

`quantagent/tools/sector_analysis.py`

Tools for analyzing market sectors — which parts of the economy are leading, which are lagging, and how money is flowing between them. These tools use the 11 SPDR sector ETFs as proxies for each sector, making them fast and efficient to run.

The 11 GICS sectors and their ETFs:
- Technology (XLK), Healthcare (XLV), Financials (XLF)
- Consumer Discretionary (XLY), Consumer Staples (XLP)
- Energy (XLE), Industrials (XLI), Materials (XLB)
- Real Estate (XLRE), Utilities (XLU), Communication Services (XLC)

---

## get_sector_performance_ranked

**Agent tool:** `get_sector_performance_ranked`

Ranks all 11 sectors by their performance across multiple timeframes.

### What It Does

Shows you which sectors are hot and which are not. It ranks sectors by their average performance across multiple timeframes (1 day, 1 week, 1 month, 3 months, 6 months, 1 year), giving you a comprehensive view of sector leadership.

### How It Works

1. **Download sector data** — fetches 2 years of price history for all 11 sector ETFs in one batch
2. **Calculate returns** — computes percentage returns for each timeframe
3. **Rank per timeframe** — ranks sectors within each timeframe (rank 1 = best performer)
4. **Average the ranks** — computes the average rank across all timeframes
5. **Final ranking** — ranks sectors by their average rank

**Why average ranks?** A sector that's consistently good across multiple timeframes is more reliable than one that had a great month but is terrible otherwise.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `periods` | `list[str] \| None` | `None` | Timeframes to analyze (defaults to all six: 1d, 1w, 1m, 3m, 6m, 1y) |

### Returns

A DataFrame with columns:
- `sector` — sector name
- `etf` — ETF ticker
- One column per timeframe (e.g. `1d`, `1w`, `1m`, etc.) showing returns as decimals
- `rank` — overall rank (1 = best)

### Usage

**Python API:**
```python
df = await get_sector_performance_ranked(provider, periods=["1m", "3m", "6m"])
```

**Agent tool:**
```
get_sector_performance_ranked(periods="1m,3m,6m")
```

The agent tool takes periods as a comma-separated string. An empty string uses all six periods.

---

## get_industry_performance

**Agent tool:** `get_industry_performance`

Drills down into a specific sector to see which industries within it are performing best.

### What It Does

Sectors are broad (Technology includes everything from Apple to Nvidia to Microsoft). Industries are more specific (Semiconductors, Software, IT Services, etc.). This tool shows you which industries within a sector are leading.

### How It Works

1. **Classify stocks** — assigns each stock in the universe to a sector and industry
2. **Filter by sector** — keeps only stocks in the requested sector
3. **Calculate returns** — computes 1-month and 3-month returns for each stock
4. **Aggregate by industry** — averages returns within each industry
5. **Rank** — ranks industries by 3-month return

**Slow on first run:** This tool needs to classify every stock in the universe (typically 500+ stocks), which can take minutes on a cold cache. After that, classifications are cached for 7 days, so subsequent runs are fast.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `sector` | `str` | required | Sector name (e.g. "Technology", "Healthcare") |
| `symbols` | `list[str] \| None` | `None` | Universe to analyze (defaults to S&P 500) |

### Returns

A DataFrame with columns:
- `industry` — industry name
- `n_stocks` — number of stocks in that industry
- `1m` — 1-month average return
- `3m` — 3-month average return
- `rank` — rank by 3-month return (1 = best)

### Usage

**Python API:**
```python
df = await get_industry_performance(provider, sector="Technology")
```

**Agent tool:**
```
get_industry_performance(sector="Technology")
```

The agent tool always analyzes the S&P 500. It uses an extended timeout due to the classification cost.

---

## classify_symbols

**Agent tool:** Not exposed to agent (internal helper)

Assigns stocks to sectors and industries using the data provider's classification endpoint.

### What It Does

Takes a list of stock tickers and returns their sector and industry classifications. This is used internally by other tools that need to group stocks by sector or industry.

### How It Works

1. **Check cache** — looks up each symbol in the cache (7-day TTL)
2. **Fetch missing** — for symbols not in cache, calls the provider's classification endpoint
3. **Cache results** — stores new classifications in the cache
4. **Return mappings** — returns a dictionary mapping symbol → {sector, industry}

**Bounded concurrency:** Limits to 8 simultaneous requests to avoid hitting rate limits. Progress is reported every 25 symbols so you know it's still working.

### Parameters

| Name | Type | Description |
|------|------|-------------|
| `provider` | `AbstractDataProvider` | Your data provider |
| `symbols` | `list[str]` | List of stock tickers |

### Returns

A dictionary mapping symbol → classification dict:
```json
{
  "AAPL": {"sector": "Technology", "industry": "Consumer Electronics"},
  "MSFT": {"sector": "Technology", "industry": "Software"},
  "XOM": {"sector": "Energy", "industry": "Oil & Gas"}
}
```

### Usage

```python
classifications = await classify_symbols(provider, ["AAPL", "MSFT", "XOM"])
```

---

## compute_sector_relative_strength

**Agent tool:** `compute_sector_relative_strength`

Measures how much each sector is outperforming or underperforming a benchmark, and whether that outperformance is improving or fading.

### What It Does

Compares each sector's performance to a benchmark (usually SPY) and tells you:
- **RS ratio** — is the sector beating the benchmark? (>1 = outperforming, <1 = underperforming)
- **Trend** — is the outperformance getting better or worse?

### How It Works

1. **Calculate returns** — computes sector and benchmark returns over the chosen period
2. **Compute RS ratio** — sector return / benchmark return
3. **Determine trend** — compares current RS to RS from 21 sessions ago
   - If RS improved by >0.01 → "improving"
   - If RS declined by >0.01 → "deteriorating"
   - Otherwise → "neutral"
4. **Rank** — ranks sectors by RS ratio

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `sectors` | `list[str] \| None` | `None` | Sectors to analyze (defaults to all 11) |
| `benchmark` | `str` | `"SPY"` | Benchmark symbol |
| `period` | `str` | `"3m"` | Timeframe (1w, 1m, 3m, 6m, 1y) |

### Returns

A DataFrame with columns:
- `sector` — sector name
- `etf` — ETF ticker
- `rs_ratio` — relative strength ratio (>1 = outperforming)
- `trend` — "improving", "deteriorating", or "neutral"
- `rs_rank` — rank by RS ratio (1 = strongest)

### Usage

**Python API:**
```python
df = await compute_sector_relative_strength(provider, benchmark="SPY", period="3m")
```

**Agent tool:**
```
compute_sector_relative_strength(benchmark="SPY", period="3m")
```

The agent tool always analyzes all 11 sectors.

---

## detect_sector_rotation

**Agent tool:** `detect_sector_rotation`

Identifies which sectors are leading/lagging and improving/deteriorating, and estimates which phase of the economic cycle the market is in.

### What It Does

Sector rotation is the tendency for different sectors to lead at different points in the economic cycle. This tool:
- Identifies the top 3 and bottom 3 sectors by relative strength
- Identifies sectors that are improving or deteriorating (momentum > 0.02 or < -0.02)
- Determines if money is flowing into cyclicals (risk-on) or defensives (risk-off)
- Estimates the current economic cycle phase

### The Four Cycle Phases

| Phase | Leading Sectors |
|-------|----------------|
| Early Recovery | Financials, Consumer Discretionary, Real Estate, Industrials |
| Mid-Expansion | Technology, Communication Services, Industrials |
| Late Cycle | Energy, Materials, Consumer Staples, Healthcare |
| Recession | Utilities, Consumer Staples, Healthcare |

### How It Works

1. **Calculate momentum** — for each sector, computes the change in RS ratio over the lookback window
2. **Identify leaders/laggards** — top 3 and bottom 3 by absolute RS
3. **Identify improving/deteriorating** — sectors with momentum > 0.02 or < -0.02
4. **Determine rotation signal** — compares cyclical vs. defensive momentum
   - If cyclicals are gaining RS faster → "risk-on"
   - If defensives are gaining RS faster → "risk-off"
   - Otherwise → "neutral"
5. **Estimate cycle phase** — matches leading/improving sectors to the phase they historically lead

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `lookback_days` | `int` | `90` | Window for RS momentum calculation |

### Returns

A dictionary with:
- `leading_sectors` — top 3 sectors by RS
- `lagging_sectors` — bottom 3 sectors by RS
- `improving_sectors` — sectors with positive momentum
- `deteriorating_sectors` — sectors with negative momentum
- `rotation_signal` — "risk-on", "risk-off", or "neutral"
- `cycle_phase` — "early-recovery", "mid-expansion", "late-cycle", or "recession"
- `as_of` — date of analysis

### Usage

**Python API:**
```python
result = await detect_sector_rotation(provider, lookback_days=90)
```

**Agent tool:**
```
detect_sector_rotation(lookback_days=90)
```

---

## get_sector_etf_heatmap

**Agent tool:** Not exposed to agent

Creates a heatmap snapshot of a chosen metric across all 11 sector ETFs.

### What It Does

Generates a single-metric view of all sectors — performance, volume, volatility, or RSI — useful for visualization or programmatic analysis.

### Available Metrics

| Metric | What it measures |
|--------|------------------|
| `performance` | 1-day return |
| `volume` | Volume ratio (today / 20-day avg) |
| `volatility` | 21-day annualized volatility |
| `rsi` | 14-day RSI |

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `metric` | `str` | `"performance"` | Metric to display |

### Returns

A dictionary with:
```json
{
  "metric": "performance",
  "as_of": "2026-08-15",
  "sectors": {
    "Technology": {"etf": "XLK", "value": 0.0123},
    "Healthcare": {"etf": "XLV", "value": -0.0045},
    ...
  }
}
```

### Usage

```python
heatmap = await get_sector_etf_heatmap(provider, metric="volatility")
```

---

## compute_sector_correlation

**Agent tool:** Not exposed to agent

Computes a correlation matrix showing how the 11 sectors move together.

### What It Does

Shows which sectors tend to move in the same direction (positive correlation) or opposite directions (negative correlation). This is useful for:
- Portfolio diversification (you want low correlation between holdings)
- Understanding sector relationships

### How It Works

1. **Download sector data** — fetches price history for all 11 sector ETFs
2. **Calculate returns** — computes daily percentage returns
3. **Compute correlations** — calculates Pearson correlation between each pair of sectors

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `period` | `str` | `"6m"` | Timeframe (1m, 3m, 6m, 1y) |

### Returns

An 11×11 correlation matrix (DataFrame) where:
- Diagonal = 1.0 (each sector correlates perfectly with itself)
- Off-diagonal = correlation between sectors (-1 to +1)

### Usage

```python
corr_matrix = await compute_sector_correlation(provider, period="3m")
```

---

## Summary

These sector analysis tools help you understand where money is flowing in the market:

- **get_sector_performance_ranked** — rank sectors by performance
- **get_industry_performance** — drill down into industries within a sector
- **classify_symbols** — assign stocks to sectors and industries (internal)
- **compute_sector_relative_strength** — compare sectors to a benchmark
- **detect_sector_rotation** — identify rotation patterns and cycle phase
- **get_sector_etf_heatmap** — single-metric sector heatmap (internal)
- **compute_sector_correlation** — sector correlation matrix (internal)

Use these tools to:
- Identify which sectors are leading the market
- Understand if money is flowing into risk-on (cyclicals) or risk-off (defensives) sectors
- Estimate where we are in the economic cycle
- Find specific industries within a sector that are outperforming

Remember: sectors rotate in a somewhat predictable pattern through the economic cycle. Early in a recovery, financials and consumer discretionary tend to lead. Late in the cycle, energy and materials take over. In a recession, defensives like utilities and consumer staples hold up best.

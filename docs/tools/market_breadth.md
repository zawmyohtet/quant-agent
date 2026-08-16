# Market Breadth Tools

`quantagent/tools/market_breadth.py`

Tools for measuring the overall health and direction of the stock market. While individual stock analysis tells you about specific companies, market breadth tells you about the market as a whole — is it healthy and broad-based, or narrow and fragile?

This module implements classic market-timing methodologies from traders like William O'Neil (CANSLIM/IBD) and Martin Zweig, plus a custom composite regime score that blends multiple signals into a single "how aggressive should I be?" recommendation.

The tools are split into two speed tiers:
- **Fast path** — uses only index ETFs and a handful of tickers, completes in seconds
- **Deep path** — analyzes hundreds of stocks (like the full S&P 500), requires a cache warm-up on first use but is fast afterward

---

## count_distribution_days

**Agent tool:** `count_distribution_days`

Counts "distribution days" — down days on higher-than-normal volume — to detect institutional selling pressure.

### What It Does

A distribution day is when the market closes down 0.2% or more on higher volume than the previous day. This suggests big institutions are selling (distributing shares to retail investors). Too many distribution days in a short period signals that the market is under pressure.

### The Logic

- **Distribution day criteria:**
  - Close is down at least 0.2% from previous day
  - Volume is higher than previous day's volume

- **Signal thresholds** (over a 25-day window):
  - 5+ distribution days → "under pressure" (market is weak)
  - 3-4 distribution days → "caution" (watch closely)
  - 0-2 distribution days → "healthy" (market is strong)

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `index_symbol` | `str` | `"SPY"` | Index to analyze (SPY, QQQ, etc.) |
| `lookback_days` | `int` | `25` | Window size (trading days) |

### Returns

A dictionary with:
- `index_symbol` — which index was analyzed
- `lookback_days` — window size
- `count` — number of distribution days
- `dates` — list of distribution day dates
- `signal` — "healthy", "caution", or "under-pressure"

### Usage

**Python API:**
```python
result = await count_distribution_days(provider, index_symbol="SPY", lookback_days=25)
```

**Agent tool:**
```
count_distribution_days(index_symbol="SPY", lookback_days=25)
```

---

## detect_follow_through_day

**Agent tool:** `detect_follow_through_day`

Detects a "Follow-Through Day" — the signal that a new uptrend has begun after a correction.

### What It Does

After a market correction (a decline from a high), traders look for confirmation that the bottom is in and a new uptrend is starting. A Follow-Through Day (FTD) is that confirmation — it's the first day (on or after rally day 4) where the market gains at least 1.25% on higher volume.

### The Logic

1. **Find the correction low** — the lowest close in the lookback window
2. **Count rally days** — each day after the low is a rally day (day 1, day 2, etc.)
3. **Look for FTD** — the first day (on or after rally day 4) where:
   - Close is up at least 1.25% from previous day
   - Volume is higher than previous day

**Why day 4+?** O'Neil found that FTDs on days 1-3 are unreliable (too many false starts). Day 4 and beyond have a much better track record.

### Signal States

- `confirmed-uptrend` — FTD detected, new uptrend confirmed
- `rally-attempt` — market is rallying but no FTD yet
- `correction` — market is still in correction mode

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `index_symbol` | `str` | `"SPY"` | Index to analyze |
| `lookback_days` | `int` | `60` | Window size (trading days) |

### Returns

A dictionary with:
- `index_symbol` — which index was analyzed
- `correction_low_date` — date of the correction low
- `rally_day` — current rally day count
- `ftd_detected` — boolean, whether FTD was found
- `ftd_date` — date of FTD (if detected)
- `status` — "confirmed-uptrend", "rally-attempt", or "correction"

### Usage

**Python API:**
```python
result = await detect_follow_through_day(provider, index_symbol="SPY")
```

**Agent tool:**
```
detect_follow_through_day(index_symbol="SPY", lookback_days=60)
```

---

## compute_percent_above_ma

**Agent tool:** `compute_percent_above_ma`

Measures what percentage of stocks in a universe are trading above their moving averages — a gauge of market breadth.

### What It Does

If 80% of S&P 500 stocks are above their 200-day moving average, that's a sign of broad strength. If only 30% are above, the market is narrow and weak — even if the index itself is near highs.

### How It Works

For each stock in the universe, checks whether the latest close is above the 20-day, 50-day, and 200-day simple moving averages. Reports the percentage of stocks above each MA.

**Fast path vs. deep path:**
- For `sector_etfs` (11 ETFs) — fetches data directly, always fast
- For `sp500` or `nasdaq100` (hundreds of stocks) — uses the BreadthStore cache. If the cache is cold and `allow_warmup=False`, falls back to the sector ETF proxy instead of blocking.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `universe` | `str` | `"sector_etfs"` | Universe to analyze |
| `ma_periods` | `list[int]` | `[20, 50, 200]` | Moving average periods |
| `allow_warmup` | `bool` | `True` | Allow cache warm-up if needed |

### Returns

A dictionary with:
- `universe` — which universe was analyzed
- `proxy` — boolean, whether a proxy was used (true if cache was cold)
- `n_symbols` — number of symbols analyzed
- `pct_above` — dictionary mapping period → percentage (e.g. `{20: 65.2, 50: 58.1, 200: 72.4}`)

### Usage

**Python API:**
```python
result = await compute_percent_above_ma(provider, universe="sp500", allow_warmup=False)
```

**Agent tool:**
```
compute_percent_above_ma(universe="sp500")
```

The agent tool always uses `allow_warmup=False` to avoid blocking on a slow cache warm-up.

---

## compute_advance_decline

**Agent tool:** `compute_advance_decline`

Computes the advance/decline line — the running total of (advancing stocks - declining stocks) each day.

### What It Does

The advance/decline (A/D) line is one of the oldest and most direct measures of market breadth. If the A/D line is rising, more stocks are advancing than declining — the market is broad and healthy. If the A/D line is falling while the index is rising, that's a bearish divergence — the rally is narrow and fragile.

### How It Works

For each day:
1. Count how many stocks advanced (close > previous close)
2. Count how many stocks declined (close < previous close)
3. Compute net advancing = advancing - declining
4. Add to the running total (cumulative sum)

Also computes 10-day and 20-day moving averages of the A/D line for trend analysis.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `universe` | `str` | `"sp500"` | Universe to analyze |
| `period` | `str` | `"3m"` | History window (1m, 3m, 6m, 1y) |

### Returns

A DataFrame with columns:
- `Advancing` — count of advancing stocks
- `Declining` — count of declining stocks
- `Unchanged` — count of unchanged stocks
- `NetAdvancing` — advancing - declining
- `ADLine` — cumulative advance/decline line
- `ADLine_SMA10` — 10-day moving average of A/D line
- `ADLine_SMA20` — 20-day moving average of A/D line

### Usage

**Python API:**
```python
df = await compute_advance_decline(provider, universe="sp500", period="3m")
```

**Agent tool:**
```
compute_advance_decline(universe="sp500", period="3m")
```

The agent tool returns the latest values and the last 10 rows of history.

---

## compute_new_highs_lows

**Agent tool:** `compute_new_highs_lows`

Counts how many stocks are making new 52-week highs vs. new 52-week lows each day.

### What It Does

A healthy market has more stocks making new highs than new lows. When new lows exceed new highs, that's a sign of weakness — even if the index itself is still near highs.

### How It Works

For each stock, computes a rolling 252-day (1-year) high and low. Then counts:
- **NewHighs** — stocks where today's close >= the 252-day high
- **NewLows** — stocks where today's close <= the 252-day low

Also computes:
- **NetNewHighs** — new highs - new lows
- **HighLowRatio** — new highs / (new highs + new lows)
- **HL_SMA10** — 10-day moving average of the ratio

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `universe` | `str` | `"sp500"` | Universe to analyze |
| `period` | `str` | `"3m"` | History window (1m, 3m, 6m, 1y) |

### Returns

A DataFrame with columns:
- `NewHighs` — count of new 52-week highs
- `NewLows` — count of new 52-week lows
- `NetNewHighs` — new highs - new lows
- `HighLowRatio` — ratio of new highs to total
- `HL_SMA10` — 10-day moving average of ratio

### Usage

**Python API:**
```python
df = await compute_new_highs_lows(provider, universe="sp500", period="3m")
```

**Agent tool:**
```
compute_new_highs_lows(universe="sp500", period="3m")
```

---

## compute_breadth_thrust

**Agent tool:** `compute_breadth_thrust`

Computes a McClellan-style breadth oscillator to detect broad, forceful market moves.

### What It Does

The breadth thrust measures the momentum of net advancing issues. A high positive thrust means the market is rising broadly and forcefully — a bullish signal. A negative thrust means the market is falling broadly — bearish.

### How It Works

1. Compute daily net advancing issues (advancing - declining)
2. Normalize by total active issues (advancing + declining)
3. Scale by 1000 (for readability)
4. Compute 19-day and 39-day exponential moving averages
5. Thrust = EMA19 - EMA39

**Signal thresholds:**
- Thrust > 50 → "bullish"
- Thrust < -50 → "bearish"
- Otherwise → "neutral"

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `universe` | `str` | `"sp500"` | Universe to analyze |
| `period` | `str` | `"3m"` | History window |

### Returns

A dictionary with:
- `thrust_value` — latest thrust value
- `thrust_signal` — "bullish", "bearish", or "neutral"
- `history` — DataFrame with NetRatio, EMA19, EMA39, Oscillator columns

### Usage

**Python API:**
```python
result = await compute_breadth_thrust(provider, universe="sp500", period="3m")
```

**Agent tool:**
```
compute_breadth_thrust(universe="sp500", period="3m")
```

---

## detect_market_regime

**Agent tool:** `detect_market_regime`

Produces a composite 0-100 market regime score with a recommended equity exposure range.

### What It Does

Combines nine different market signals into a single score that tells you "how aggressive should I be right now?" The score maps to a regime label (strong-bull, bull, neutral, bear, strong-bear) and a recommended equity exposure range (e.g. 70-90% for bull).

### The Nine Components

| Component | Weight | What it measures |
|-----------|--------|------------------|
| Concentration (RSP/SPY) | 10% | Equal-weight vs. cap-weight performance |
| Size (IWM/SPY) | 10% | Small-cap vs. large-cap performance |
| Cyclical/Defensive (XLY/XLP) | 10% | Risk-on vs. risk-off sector rotation |
| Stock/Bond (SPY/TLT) | 10% | Stocks vs. bonds performance |
| Credit (HYG/LQD) | 10% | High-yield vs. investment-grade credit |
| Trend (SPY vs. 50/200 SMA) | 20% | Price trend (double weight!) |
| Volatility (VIX level) | 10% | Market fear gauge |
| Breadth (% above 50-SMA) | 10% | Market participation |
| Participation (% sectors positive) | 10% | Sector breadth |

### How It Works

1. **Compute each component** — each signal is scored from -1 (very bearish) to +1 (very bullish)
2. **Weighted average** — multiply each score by its weight, sum them up
3. **Map to 0-100** — composite = 50 × (1 + weighted_average)
4. **Determine regime** — based on score thresholds (80+, 60+, 40+, 20+, <20)
5. **Calculate confidence** — what fraction of components agree with the overall direction

### Regime Bands

| Score | Regime | Exposure | Label |
|-------|--------|----------|-------|
| 80+ | strong-bull | 90-100% | strong |
| 60-79 | bull | 70-90% | healthy |
| 40-59 | neutral | 50-70% | neutral |
| 20-39 | bear | 40-60% | weakening |
| <20 | strong-bear | 25-40% | critical |

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `universe` | `str` | `"sp500"` | Universe for breadth analysis |

### Returns

A dictionary with:
- `regime` — regime label
- `score` — 0-100 composite score
- `confidence` — 0-1 confidence level
- `recommended_exposure` — {min_pct, max_pct, label}
- `components` — detailed breakdown of each signal
- `as_of` — date of analysis

### Usage

**Python API:**
```python
result = await detect_market_regime(provider, universe="sp500")
```

**Agent tool:**
```
detect_market_regime()
```

The agent tool always uses `universe="sp500"` and cannot be changed.

---

## compute_market_sentiment

**Agent tool:** `compute_market_sentiment`

Computes a "fear & greed" style sentiment score from -100 (extreme fear) to +100 (extreme greed).

### What It Does

Combines four sentiment indicators into a single score:
1. **VIX level** — low VIX = greed, high VIX = fear
2. **VIX term structure** — contango = normal, backwardation = stress
3. **Sector breadth** — % of sector ETFs above 50-day MA
4. **Momentum** — SPY 1-month and 3-month returns

### Signal Thresholds

| Score | Label |
|-------|-------|
| 60+ | extreme-greed |
| 20-59 | greed |
| -19 to 19 | neutral |
| -60 to -20 | fear |
| < -60 | extreme-fear |

### Parameters

| Name | Type | Description |
|------|------|-------------|
| `provider` | `AbstractDataProvider` | Your data provider |

### Returns

A dictionary with:
- `score` — -100 to +100 sentiment score
- `label` — sentiment label
- `components` — breakdown of each indicator

### Usage

**Python API:**
```python
result = await compute_market_sentiment(provider)
```

**Agent tool:**
```
compute_market_sentiment()
```

---

## Summary

These market breadth tools help you understand the overall health of the market:

- **count_distribution_days** — detect institutional selling pressure
- **detect_follow_through_day** — confirm new uptrends
- **compute_percent_above_ma** — measure market participation
- **compute_advance_decline** — track advancing vs. declining stocks
- **compute_new_highs_lows** — count new 52-week highs/lows
- **compute_breadth_thrust** — detect broad, forceful moves
- **detect_market_regime** — composite regime score with exposure guidance
- **compute_market_sentiment** — fear & greed sentiment score

Use these tools together to get a complete picture of market health. A market with strong breadth (high % above MAs, rising A/D line, more new highs than lows) is healthy and sustainable. A market with weak breadth (low % above MAs, falling A/D line, more new lows than highs) is fragile and at risk of reversal.

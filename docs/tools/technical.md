# Technical Analysis Tools

`quantagent/tools/technical.py`

Tools for analyzing price action — the study of what prices are doing right now, rather than what companies are worth. Technical analysis assumes that all known information is already reflected in the price, so by studying price patterns, trends, and momentum, you can gauge supply and demand dynamics.

This module is the price-action toolbox: it computes standard indicators (moving averages, RSI, MACD, Bollinger Bands), detects candlestick patterns and support/resistance levels, generates trading signals for backtesting, and summarizes everything into compact snapshots the agent can reason about.

All tools here work with OHLCV DataFrames (Open, High, Low, Close, Volume) — the standard format for price data.

---

## compute_indicators

**Agent tool:** `compute_technical_indicators`

Computes one or more technical indicators and adds them as columns to your price data.

### What It Does

Takes a stock's price history and computes technical indicators like:
- **Moving averages** (SMA, EMA) — smooth out price to see the trend
- **Oscillators** (RSI, MACD, Stochastic) — measure momentum and overbought/oversold conditions
- **Volatility bands** (Bollinger Bands, ATR) — measure how much the price is moving
- **Volume indicators** (OBV, VWAP) — confirm trends with volume
- **Trend indicators** (ADX, Supertrend) — measure trend strength and direction

### How It Works

Instead of implementing each indicator from scratch, the tool uses `pandas-ta`, a well-maintained library with 100+ technical indicators. You specify which indicators you want using simple strings like `"rsi_14"` or `"sma_20"`, and the tool delegates to pandas-ta for the actual computation.

The tool is fault-tolerant: if one indicator fails (maybe you typo'd the name, or there's not enough data), it logs a warning and continues with the others. One bad indicator won't crash the whole request.

### Available Indicators

| Indicator | Spec string | Description |
|-----------|-------------|-------------|
| Simple Moving Average | `sma_N` | Average of last N prices (e.g. `sma_20`, `sma_50`) |
| Exponential Moving Average | `ema_N` | Weighted average, more responsive to recent prices |
| Relative Strength Index | `rsi_N` | Momentum oscillator (0-100), overbought >70, oversold <30 |
| MACD | `macd` | Trend + momentum (uses defaults: fast=12, slow=26, signal=9) |
| Bollinger Bands | `bbands` | Volatility bands around a moving average (default: 20-period, 2 std dev) |
| Average True Range | `atr_N` | Volatility measure (average of true ranges over N periods) |
| Average Directional Index | `adx_N` | Trend strength (not direction), >25 = strong trend |
| On-Balance Volume | `obv` | Cumulative volume indicator |
| Stochastic | `stoch_k` / `stoch_d` | Momentum oscillator comparing close to range |
| Volume Weighted Avg Price | `vwap` | Average price weighted by volume |
| Supertrend | `supertrend` | Trend-following overlay (default: ATR 7, multiplier 3) |

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `df` | `pd.DataFrame` | required | OHLCV price data |
| `indicators` | `list[str]` | required | List of indicator spec strings |

### Returns

The input DataFrame with indicator columns appended. The original data is not modified (a copy is made first).

### Usage

**Python API:**
```python
df_with_indicators = compute_indicators(df, ["sma_20", "rsi_14", "macd", "bbands"])
```

**Agent tool:**
```
compute_technical_indicators(symbol="AAPL", indicators="sma_20, rsi_14, macd, bbands")
```

The agent tool fetches 1 year of daily data, computes the indicators, and returns just the latest row (not the full history).

---

## detect_patterns

**Agent tool:** `detect_chart_patterns`

Scans price history for classic candlestick patterns like doji, engulfing, hammer, morning star, etc.

### What It Does

Identifies candlestick patterns that traders believe signal potential reversals or continuations. These are visual patterns in the price data that have been studied for centuries.

### Available Patterns

| Pattern | Candles | Direction | What it suggests |
|---------|---------|-----------|------------------|
| Doji | 1 | Neutral | Indecision — buyers and sellers are balanced |
| Hammer | 1 | Bullish | Potential reversal after downtrend |
| Shooting Star | 1 | Bearish | Potential reversal after uptrend |
| Bullish Engulfing | 2 | Bullish | Strong reversal signal |
| Bearish Engulfing | 2 | Bearish | Strong reversal signal |
| Morning Star | 3 | Bullish | Reversal from downtrend |
| Evening Star | 3 | Bearish | Reversal from uptrend |
| Three White Soldiers | 3 | Bullish | Strong continuation |
| Three Black Crows | 3 | Bearish | Strong continuation |

### How It Works

The tool uses vectorized pandas/numpy operations to scan the entire price history at once. Each pattern is defined by a set of boolean conditions on the candle geometry (body size, shadow lengths, relationship to prior candles).

**Important caveat:** The patterns are purely shape-based — they don't consider the broader trend context. For example, a "hammer" is detected based on its shape alone, not whether it appears after a downtrend (where it would be more meaningful). Treat these as candidate patterns, not confirmed signals.

### Parameters

| Name | Type | Description |
|------|------|-------------|
| `df` | `pd.DataFrame` | OHLCV price data (needs at least 3 bars) |

### Returns

A list of detected patterns, each with:
- `pattern` — pattern name (e.g. "bullish_engulfing")
- `date` — when it occurred
- `direction` — "bullish", "bearish", or "neutral"
- `strength` — 1 (single candle), 2 (two candles), or 3 (three candles)

Sorted most recent first.

### Usage

**Python API:**
```python
patterns = detect_patterns(df)
```

**Agent tool:**
```
detect_chart_patterns(symbol="NVDA")
```

The agent tool fetches 3 months of data and returns the 10 most recent patterns.

---

## detect_support_resistance

**Agent tool:** `get_support_resistance`

Identifies key price levels where the stock has historically found buyers (support) or sellers (resistance).

### What It Does

Finds "pivot points" — local highs and lows in the price data — and clusters nearby levels together. Support levels are where buyers have stepped in before; resistance levels are where sellers have emerged.

### How It Works

1. **Find pivots** — a bar's low is a support pivot if it's the lowest point in a rolling window AND lower than both neighbors. Resistance pivots are the mirror image (local highs).
2. **Deduplicate** — nearby levels (within 1% of each other) are merged into a single level
3. **Return top 5** — the five highest support levels and five highest resistance levels

The window size auto-shrinks for short histories, so the tool works even with limited data.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `df` | `pd.DataFrame` | required | OHLCV price data |
| `window` | `int` | `20` | Rolling window size for pivot detection |

### Returns

A dictionary with:
- `support` — list of support levels (floats)
- `resistance` — list of resistance levels (floats)
- `current_price` — latest close price

### Usage

**Python API:**
```python
levels = detect_support_resistance(df, window=20)
```

**Agent tool:**
```
get_support_resistance(symbol="MSFT")
```

The agent tool fetches 6 months of data and uses the default 20-bar window.

---

## wilder_rsi

**Agent tool:** Not exposed to agent (internal helper)

A fast, lightweight RSI calculation used by screeners and other tools that need to compute RSI for many stocks.

### What It Does

Computes the Relative Strength Index (RSI) — a momentum oscillator that measures the speed and magnitude of price changes. RSI ranges from 0 to 100:
- Above 70 = overbought (might pull back)
- Below 30 = oversold (might bounce)

### How It Works

Uses Wilder's smoothing method (exponential moving average) to calculate average gains and losses, then computes RSI as:

```
RS = average_gain / average_loss
RSI = 100 - (100 / (1 + RS))
```

This is a simplified, dependency-free implementation that takes just a Close price series (no need for full OHLCV data). It's optimized for speed when screening hundreds of stocks.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `close` | `pd.Series` | required | Close price series |
| `length` | `int` | `14` | RSI period |

### Returns

A single float (the latest RSI value) rounded to 4 decimals, or `None` if there isn't enough data.

### Usage

```python
rsi = wilder_rsi(close_series, length=14)
```

---

## generate_signals

**Agent tool:** Not exposed to agent (used by backtesting tools)

Converts price history into buy/sell/hold signals for backtesting.

### What It Does

Takes a trading strategy (like "buy when the 50-day SMA crosses above the 200-day SMA") and generates a signal for each day: 1 (buy), -1 (sell), or 0 (hold). The backtester then uses these signals to simulate trades.

### Available Strategies

| Strategy | Logic | Default parameters |
|----------|-------|-------------------|
| `sma_crossover` | Buy when fast SMA > slow SMA | fast=50, slow=200 |
| `ema_crossover` | Buy when fast EMA > slow EMA | fast=12, slow=26 |
| `rsi_mean_reversion` | Buy when RSI < oversold, sell when RSI > overbought | length=14, oversold=30, overbought=70 |
| `macd_momentum` | Buy when MACD > signal line | fast=12, slow=26, signal=9 |
| `bollinger_breakout` | Buy when price > upper band, sell when < lower band | length=20 |
| `buy_and_hold` | Buy on day 1, hold forever | (no parameters) |

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `df` | `pd.DataFrame` | required | OHLCV price data |
| `strategy` | `str` | required | Strategy name |
| `params` | `dict \| None` | `None` | Optional parameter overrides |

### Returns

The input DataFrame with a `Signal` column added (1, -1, or 0 for each day).

### Usage

```python
signals_df = generate_signals(df, strategy="sma_crossover", params={"fast": 20, "slow": 50})
```

---

## compute_correlation_matrix

**Agent tool:** Not exposed to agent

Computes a correlation matrix showing how a set of stocks move together.

### What It Does

Given price data for multiple stocks, computes the Pearson correlation coefficient between each pair. Correlation ranges from -1 (perfect inverse relationship) to +1 (perfect positive relationship).

This is useful for:
- Portfolio diversification (you want low correlation between holdings)
- Pair trading (finding stocks that move together)

### Parameters

| Name | Type | Description |
|------|------|-------------|
| `dfs` | `dict[str, pd.DataFrame]` | Mapping of symbol → OHLCV DataFrame |

### Returns

A symbol × symbol correlation matrix (DataFrame).

### Usage

```python
corr_matrix = compute_correlation_matrix({"AAPL": aapl_df, "MSFT": msft_df, "GOOG": goog_df})
```

---

## summarize_technicals

**Agent tool:** Not exposed to agent (used by report generators)

Creates a compact technical snapshot — trend, momentum, volatility, and volume — in a single dictionary.

### What It Does

Computes a handful of key indicators and packages them into a summary:
- **Trend** — SMA 20/50/200 values, whether price is above SMA 200
- **Momentum** — RSI, MACD signal (bullish/bearish)
- **Volatility** — Bollinger Band position, ATR, ADX
- **Volume** — 20-day average volume, latest volume

### How It Works

Computes each indicator once using pandas-ta, then extracts the latest value. Requires at least 50 bars of data (for the longer indicators to be meaningful).

### Parameters

| Name | Type | Description |
|------|------|-------------|
| `df` | `pd.DataFrame` | OHLCV price data (needs >= 50 bars) |

### Returns

A dictionary with:
```json
{
  "price": 150.25,
  "trend": {"sma20": 148.5, "sma50": 145.2, "sma200": 140.1, "above_sma200": true},
  "momentum": {"rsi": 62.4, "macd_signal": "bullish"},
  "volatility": {"bb_position": 0.72, "atr": 3.45, "adx": 28.3},
  "volume": {"avg_volume_20d": 1234567, "latest_volume": 1500000}
}
```

Or `{"error": "Insufficient data (need >= 50 bars)"}` if the input is too short.

### Usage

```python
summary = summarize_technicals(df)
```

---

## Summary

These technical analysis tools help you understand what prices are doing:

- **compute_indicators** — compute any technical indicator you need
- **detect_patterns** — find candlestick patterns
- **detect_support_resistance** — identify key price levels
- **wilder_rsi** — fast RSI for screening
- **generate_signals** — create trading signals for backtesting
- **compute_correlation_matrix** — see how stocks move together
- **summarize_technicals** — get a compact technical snapshot

Use these tools to gauge market sentiment, identify entry/exit points, and confirm trends. Remember: technical analysis is about probabilities, not certainties. Patterns and indicators give you an edge, but they don't guarantee outcomes.

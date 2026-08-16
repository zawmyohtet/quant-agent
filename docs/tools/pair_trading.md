# Pair Trading Tools

`quantagent/tools/pair_trading.py`

Tools for statistical arbitrage — finding pairs of stocks that move together and trading the spread between them when it deviates from normal. This is a market-neutral strategy: you're not betting on the market going up or down, just on the relationship between two specific stocks returning to normal.

---

## find_cointegrated_pairs

**Agent tool:** `find_cointegrated_pairs`

Scans a universe of stocks to find pairs that are statistically "cointegrated" — meaning they tend to move together over time and any deviations from their normal relationship are temporary.

### What It Does

Finds pairs of stocks that are good candidates for pair trading. Two stocks are cointegrated if:
- They're highly correlated (move in the same direction)
- The spread between them is mean-reverting (when it deviates, it tends to come back)

### How It Works

1. **Download price data** — fetches historical prices for all stocks in the universe
2. **Correlation filter** — quickly eliminates pairs with low correlation (< 0.7 by default)
3. **Cointegration test** — for pairs that pass the correlation filter, runs the Engle-Granger test to check if the spread is mean-reverting
4. **Calculate metrics** — for cointegrated pairs, computes hedge ratio, half-life, and current z-score
5. **Rank and return** — sorts by cointegration strength (lowest p-value first)

**Two-stage filter:** Correlation is cheap to compute (one matrix operation), so we use it to quickly eliminate most pairs. Cointegration testing is expensive (requires regression and statistical tests for each pair), so we only run it on pairs that pass the correlation filter.

**Sector restriction recommended:** Cross-sector pairs often cointegrate by accident (e.g. two random stocks might both be trending up). Pairs within the same sector are more likely to have a genuine economic relationship.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `universe` | `str` | `"sp500"` | Universe to scan |
| `sector` | `str \| None` | `None` | Restrict to one sector |
| `max_symbols` | `int` | `60` | Max symbols to scan (pair count grows quadratically!) |
| `pvalue_threshold` | `float` | `0.05` | Max p-value for cointegration test |
| `min_correlation` | `float` | `0.7` | Min correlation for pre-filter |
| `limit` | `int` | `20` | Max pairs to return |

### Returns

A DataFrame with columns:
- `symbol_a`, `symbol_b` — the pair
- `correlation` — Pearson correlation
- `coint_pvalue` — p-value from cointegration test (lower = stronger)
- `hedge_ratio` — how many shares of B to short for each share of A long
- `half_life_days` — how long it takes for the spread to revert halfway to the mean
- `current_zscore` — current standardized value of the spread
- `spread_mean`, `spread_std` — historical mean and standard deviation of the spread

### Usage

**Python API:**
```python
df = await find_cointegrated_pairs(
    provider,
    universe="sp500",
    sector="Energy",
    max_symbols=40,
    pvalue_threshold=0.05,
    min_correlation=0.7,
    limit=10
)
```

**Agent tool:**
```
find_cointegrated_pairs(universe="sp500", sector="Energy", max_symbols=40, limit=10)
```

The agent tool fixes `pvalue_threshold` at 0.05 and `min_correlation` at 0.7. It uses an extended timeout due to the computational cost.

---

## compute_spread_metrics

**Agent tool:** `compute_spread_metrics`

Analyzes a specific pair of stocks to determine if the spread is currently tradeable.

### What It Does

Given two stocks you've already identified as a pair, this tool:
- Calculates the hedge ratio (how to balance the trade)
- Tests if the spread is cointegrated (mean-reverting)
- Computes the current z-score (how far the spread is from normal)
- Estimates the half-life (how long until the spread reverts)
- Generates a trading signal

### The Math

**Hedge ratio (OLS regression):**
```
spread = price_a - beta * price_b
```
Where beta is the slope from regressing A's price on B's price. This tells you how many shares of B to short for each share of A you go long.

**Z-score:**
```
zscore = (current_spread - mean_spread) / std_spread
```
Measures how many standard deviations the current spread is from its historical mean.

**Half-life:**
Fits an AR(1) model to the spread to estimate how quickly it mean-reverts:
```
half_life = -ln(2) / lambda
```
Where lambda is the mean-reversion speed. A half-life of 10 days means the spread typically takes 10 days to revert halfway to the mean.

**Cointegration test:**
Uses the Engle-Granger two-step procedure:
1. Regress one series on the other to get the spread
2. Test if the spread has a unit root (non-stationary) using an ADF-style test
3. Rejecting the unit root (low p-value) implies the spread is stationary (mean-reverting)

### Trading Signals

| Z-Score | Signal | Action |
|---------|--------|--------|
| >= 2 | Entry zone (spread rich) | Short A, long B |
| <= -2 | Entry zone (spread cheap) | Long A, short B |
| abs(z) <= 0.5 | Exit zone | Close the position |
| Otherwise | Neutral | Wait |

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `symbol_a` | `str` | required | First stock |
| `symbol_b` | `str` | required | Second stock |
| `period` | `str` | `"1y"` | History window (6mo, 1y, 2y) |

### Returns

A dictionary with:
```json
{
  "symbol_a": "XOM",
  "symbol_b": "CVX",
  "correlation": 0.8821,
  "coint_pvalue": 0.0231,
  "hedge_ratio": 1.1024,
  "half_life_days": 18.42,
  "current_zscore": 2.13,
  "spread_mean": 4.5012,
  "spread_std": 2.209,
  "signal": "entry-zone: spread rich — short XOM, long CVX"
}
```

### Usage

**Python API:**
```python
result = await compute_spread_metrics(provider, "XOM", "CVX", period="1y")
```

**Agent tool:**
```
compute_spread_metrics(symbol_a="XOM", symbol_b="CVX", period="1y")
```

### Design Notes

**Minimum data requirement:** The tool requires at least 120 aligned trading sessions (about 6 months) of overlapping data. If there isn't enough data, it raises a `ValueError` rather than returning unreliable results.

**Degenerate spreads:** If the spread has zero or NaN standard deviation (e.g. two nearly identical stocks), the tool raises a `ValueError`. A pair trading tool giving a confident z-score off insufficient data is worse than one that refuses to answer.

**Symbol normalization:** Symbols are upper-cased defensively since tickers may arrive in any case from an agent or user.

---

## Summary

These pair trading tools help you find and analyze statistical arbitrage opportunities:

- **find_cointegrated_pairs** — scan a universe to find cointegrated pairs
- **compute_spread_metrics** — analyze a specific pair for trading

Use these tools to:
- Find pairs of stocks that move together (like Coca-Cola and Pepsi, or Exxon and Chevron)
- Determine if the spread between them is currently tradeable
- Calculate the right hedge ratio to balance the trade
- Estimate how long it will take for the spread to revert

Remember: pair trading is market-neutral — you're not betting on the market direction, just on the relationship between two stocks returning to normal. This can work in any market environment, but it requires careful risk management and position sizing.

The key insight is that cointegration is different from correlation. Two stocks can be highly correlated but not cointegrated (they both trend up but the spread between them keeps growing). Only cointegrated pairs have a mean-reverting spread that can be traded.

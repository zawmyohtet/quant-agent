# Screener Tools

`quantagent/tools/screener.py`

Stock screening is the process of filtering a large universe of stocks (like the S&P 500) down to a smaller list that meets specific criteria. Instead of manually researching hundreds of companies, you define what you're looking for — cheap valuation, strong profitability, technical momentum, a specific chart pattern — and the screener does the work for you.

QuantAgent offers several types of screens, each designed for a different investment approach:

- **Fundamental screens** — filter by valuation, profitability, growth, and financial health metrics
- **Technical screens** — filter by price action, momentum, and volume patterns
- **Pattern screens** — filter for specific chart patterns (VCP, breakouts, oversold reversals)
- **Combined screens** — apply both fundamental and technical filters together

---

## How Screening Works

### Data Fetching Strategy

The screener uses two different approaches depending on the type of screen:

**Fundamental screens** fetch data for each stock individually — company financials, current quote, valuation ratios. Since these are separate API calls, the screener runs them in parallel with a limit of 8 concurrent requests. This keeps the screen fast while respecting your data provider's rate limits.

**Technical and pattern screens** work differently. They download price history for the entire universe in one batch operation, then evaluate all the technical criteria locally on your computer. This is much more efficient than making hundreds of individual API calls for each stock's price history.

### Graceful Failure

When screening hundreds of stocks, some will inevitably fail to download — maybe the ticker symbol is invalid, maybe the data provider had a temporary error, maybe the stock was recently delisted. The screener handles this gracefully: it logs the error, skips that stock, and continues with the rest.

This means a screen might return 495 results instead of 500 if 5 stocks failed to download. That's usually fine — you're looking for the best candidates, not a perfect list. If the entire universe fails to load (for example, if you misspelled the universe name), the screener returns an empty result.

---

## Fundamental Screening

### screen_stocks

**Agent tool:** `screen_stocks_tool`

This is the classic "find me good companies" screen. You specify what you're looking for — cheap valuation, strong profitability, low debt, good growth — and the screener filters the universe down to stocks that meet all your criteria.

#### How It Works

1. **Resolve the universe** — the screener looks up all the stocks in the specified universe (S&P 500, Nasdaq 100, etc.). If you've specified a `max_symbols` limit, it truncates the list to that size.

2. **Fetch data** — for each stock, the screener downloads the company's fundamentals (P/E ratio, return on equity, debt-to-equity, etc.) and current quote (price, market cap, volume). These calls run in parallel with a concurrency limit of 8.

3. **Apply filters** — the screener applies each criterion you specified. All criteria are AND-ed together, meaning a stock must pass every single filter to make the final list.

4. **Sort and limit** — the results are sorted by your chosen column (default: market cap, largest first) and truncated to your specified limit (default: 20 stocks).

#### Available Criteria

You can filter by any combination of the following metrics:

| Criteria key | What it filters | Example |
|---|---|---|
| `pe_lt` / `pe_gt` | Price-to-earnings ratio | `pe_lt: 15` — P/E below 15 (cheap valuation) |
| `pb_lt` / `pb_gt` | Price-to-book ratio | `pb_lt: 1.5` — P/B below 1.5 |
| `roe_gt` | Return on equity | `roe_gt: 0.20` — ROE above 20% (profitable) |
| `roa_gt` | Return on assets | `roa_gt: 0.10` — ROA above 10% |
| `debt_equity_lt` | Debt-to-equity ratio | `debt_equity_lt: 1.0` — debt/equity below 1.0 (low leverage) |
| `mcap_gt` / `mcap_lt` | Market capitalization | `mcap_gt: 10000000000` — market cap above $10B |
| `market_cap_gt` / `market_cap_lt` | Market capitalization (alias) | Same as above |
| `volume_gt` | Trading volume | `volume_gt: 1000000` — volume above 1M shares |
| `dividend_yield_gt` | Dividend yield | `dividend_yield_gt: 0.02` — yield above 2% |
| `revenue_growth_gt` | Revenue growth rate | `revenue_growth_gt: 0.10` — revenue growing 10%+ |
| `eps_growth_gt` | Earnings per share growth | `eps_growth_gt: 0.15` — EPS growing 15%+ |
| `beta_lt` | Beta (volatility vs. market) | `beta_lt: 1.2` — beta below 1.2 (less volatile) |

You can combine as many criteria as you want. For example, to find cheap, profitable, low-debt companies:

```
criteria = {
    "pe_lt": 15,
    "roe_gt": 0.20,
    "debt_equity_lt": 1.0
}
```

This would return stocks with P/E below 15, ROE above 20%, and debt-to-equity below 1.0.

#### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Market data provider |
| `universe` | `str` | `"sp500"` | Universe to screen (sp500, nasdaq100, dow30, sector_etfs, or custom) |
| `criteria` | `dict \| None` | `None` | Filter criteria (see table above) |
| `sort_by` | `str` | `"market_cap"` | Column to sort results by |
| `ascending` | `bool` | `False` | Sort direction (False = largest first) |
| `limit` | `int` | `20` | Maximum number of results |
| `max_symbols` | `int \| None` | `None` | Optional cap on symbols to fetch (for faster screens) |

#### Returns

A table with one row per stock that passed all filters. Columns include: `symbol`, `name`, `pe_ratio`, `pb_ratio`, `roe`, `roa`, `debt_equity`, `market_cap`, `volume`, `dividend_yield`, `revenue_growth`, `eps_growth`, `beta`, `price`.

If no stocks match your criteria, or if the universe fails to load, the result is an empty table.

#### Design Notes

- **No built-in thresholds** — the screener doesn't impose any default filters. You specify exactly what you're looking for. This gives you full control, but it also means you need to know what reasonable thresholds look like (for example, a P/E below 15 is considered cheap, but a P/E below 5 might indicate a company in distress).

- **Extensible criteria** — the screener uses a lookup table to map criteria keys to columns and operators. If you want to add a new filter (for example, filtering by current ratio), you just add one line to the table. Unknown criteria keys are logged as warnings and ignored, so a typo in a criteria key won't crash the screen — it just won't filter on that criterion.

- **Progress reporting** — for large universes, the screener reports progress every 25 symbols so you know it's still working. Screening the S&P 500 typically takes 30–60 seconds depending on your data provider's speed.

---

### screen_by_fundamentals

**Agent tool:** Not exposed to agent.

This is a thin wrapper around `screen_stocks` with a larger default result set (50 stocks instead of 20). It exists for internal use by other tools that want a broader list of candidates.

The filtering logic is identical to `screen_stocks` — it just calls that function with `limit=50` instead of `limit=20`.

---

## Technical Screening

### screen_by_technicals

**Agent tool:** `screen_technicals_tool`

This screen filters stocks based on technical indicators — momentum, trend, volume patterns. It's useful for finding stocks that are showing signs of strength (or weakness) based on their price action, independent of their fundamental valuation.

#### How It Works

1. **Batch download** — the screener downloads 1 year of daily price history for the entire universe in one operation. This is much more efficient than downloading each stock's history individually.

2. **Evaluate criteria** — for each stock, the screener checks whether it meets all the technical criteria you specified. Each criterion is evaluated independently, and all criteria must be satisfied (AND logic).

3. **Handle insufficient data** — some technical indicators require a minimum amount of history. For example, MACD needs at least 35 bars of data, and a 200-day moving average needs 200 bars. If a stock doesn't have enough history to compute an indicator, the screener treats that as a failure for that criterion (the stock doesn't pass). This conservatively excludes thinly-traded or newly-listed stocks rather than guessing.

4. **Return results** — stocks that pass all criteria are returned, sorted by the order they were downloaded (no automatic sorting by a specific metric).

#### Available Criteria

| Criteria key | What it checks | Example |
|---|---|---|
| `rsi_lt` | RSI below a threshold (oversold) | `rsi_lt: 30` — RSI below 30 (oversold) |
| `rsi_gt` | RSI above a threshold (overbought) | `rsi_gt: 70` — RSI above 70 (overbought) |
| `macd_bullish` | MACD line above signal line (bullish momentum) | `macd_bullish: true` — MACD is bullish |
| `price_above_sma` | Price above a simple moving average | `price_above_sma: 200` — price above 200-day SMA |
| `price_below_sma` | Price below a simple moving average | `price_below_sma: 50` — price below 50-day SMA |
| `volume_expansion` | Volume above a multiple of 20-day average | `volume_expansion: 1.5` — volume is 1.5x the 20-day average |
| `atr_breakout` | Price above upper Bollinger band (breakout) | `atr_breakout: true` — price broke above upper band |
| `adx_gt` | ADX above a threshold (strong trend) | `adx_gt: 25` — ADX above 25 (strong trend) |

#### Understanding the Indicators

If you're not familiar with technical analysis, here's a brief explanation of each indicator:

**RSI (Relative Strength Index)** measures how overbought or oversold a stock is on a scale of 0 to 100. Above 70 is considered overbought (the stock has gone up too fast and might pull back). Below 30 is considered oversold (the stock has fallen too fast and might bounce). RSI is a momentum oscillator that helps identify potential reversal points.

**MACD (Moving Average Convergence Divergence)** compares two moving averages (12-day and 26-day EMAs) to identify momentum shifts. When the MACD line crosses above the signal line (a 9-day EMA of the MACD), that's a bullish signal — momentum is shifting upward. When it crosses below, that's bearish.

**Simple Moving Average (SMA)** is the average price over a specified period. The 200-day SMA is widely watched as a long-term trend indicator — stocks above their 200-day SMA are considered to be in an uptrend, stocks below are in a downtrend. The 50-day SMA is a shorter-term trend indicator.

**Volume expansion** measures whether today's trading volume is significantly above the recent average. High volume on an up day suggests strong buying interest (institutional money flowing in). High volume on a down day suggests strong selling pressure. Volume confirms price moves — a breakout on high volume is more convincing than a breakout on low volume.

**Bollinger Bands** are a volatility-based envelope around the price. The upper band is typically set at 2 standard deviations above the 20-day moving average. When price breaks above the upper band, that's considered a breakout — the stock is moving strongly in an upward direction. Bollinger breakouts often signal the start of a strong trend.

**ADX (Average Directional Index)** measures the strength of a trend (not the direction). ADX above 25 indicates a strong trend (either up or down). ADX below 20 indicates a weak or non-existent trend (the stock is trading sideways). ADX helps you avoid trading in choppy, trendless markets.

#### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Market data provider |
| `criteria` | `dict[str, Any]` | required | Technical criteria (see table above) |
| `universe` | `str` | `"sp500"` | Universe to screen (ignored if `symbols` is provided) |
| `symbols` | `list[str] \| None` | `None` | Explicit list of symbols to screen (e.g. pre-filtered by fundamentals) |
| `limit` | `int` | `50` | Maximum number of results |

#### Returns

A table with one row per stock that passed all criteria. Columns include: `symbol`, `price`, `rsi`, `volume_ratio`. The `rsi` and `volume_ratio` columns show the current values for those indicators, regardless of whether you filtered on them.

#### Design Notes

- **Batch-download approach** — by downloading the entire universe's price history in one operation, the screener minimizes API calls and runs much faster than if it downloaded each stock individually. For the S&P 500, this is one batch download instead of 500 individual requests.

- **Pre-filtered symbols** — the `symbols` parameter lets you pass in a list of stocks that were pre-filtered by some other process (for example, the output of a fundamental screen). This is how `screen_combined` chains fundamental and technical filters — it runs the fundamental screen first, then passes the survivors to the technical screen.

- **Unknown criteria** — if you specify a criteria key that the screener doesn't recognize, it logs a warning and treats that criterion as passing (no filtering). This means a typo in a criteria key won't crash the screen, but it also won't filter on that criterion. Always check your results to make sure they make sense.

---

## Combined Screening

### screen_combined

**Agent tool:** `screen_combined_tool`

This screen applies both fundamental and technical filters, returning only stocks that pass both. For example, you might want to find profitable, low-debt companies (fundamental) that are also showing technical strength (above their 200-day moving average with bullish MACD).

#### How It Works

1. **Run fundamental screen first** — fundamental filters are cheap (one API call per stock for fundamentals and quote), so they run first with a high internal limit (10,000) to avoid truncating the candidate pool.

2. **Pass survivors to technical screen** — only the stocks that passed the fundamental filters are then sent to the technical screen. This is much more efficient than running the technical screen on the entire universe, because technical screens require downloading price history for each stock.

3. **Merge results** — the final result is the intersection of the two screens — stocks that passed both the fundamental and technical filters.

#### Why This Order?

You might wonder why we run the fundamental screen first instead of the technical screen. The reason is efficiency:

- Fundamental screens require one API call per stock (for fundamentals and quote). For the S&P 500, that's 500 API calls.
- Technical screens require downloading price history for each stock. For the S&P 500, that's a batch download of 500 stocks' price history, which is much more data and takes longer.

By running the fundamental screen first, we typically narrow the universe from 500 stocks down to 50 or 100. Then we only need to download price history for those 50–100 stocks, not all 500. This is much faster and uses less of your data provider's quota.

#### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Market data provider |
| `technical_criteria` | `dict[str, Any] \| None` | `None` | Technical criteria (see `screen_by_technicals`) |
| `fundamental_criteria` | `dict[str, Any] \| None` | `None` | Fundamental criteria (see `screen_stocks`) |
| `universe` | `str` | `"sp500"` | Universe to screen |
| `limit` | `int` | `50` | Maximum number of results |

#### Returns

A table with one row per stock that passed both screens. Columns include all the fundamental columns from `screen_stocks` plus `rsi` and `volume_ratio` from the technical screen.

If you only provide one type of criteria (fundamental or technical), the function returns that single screen's results directly.

---

## Pattern Screens

Pattern screens look for specific chart patterns that traders believe signal future price movements. These are based on technical analysis theories developed by traders like Mark Minervini (VCP pattern) and William O'Neil (breakouts).

### screen_vcp_pattern

**Agent tool:** `screen_vcp_tool`

This screen looks for **Volatility Contraction Patterns (VCP)**, a concept developed by trader Mark Minervini. A VCP is a specific type of consolidation pattern that often precedes a breakout to new highs.

#### What Is a VCP?

Imagine a stock that had a strong uptrend over the past 9 months, gaining 30% or more. Now it's consolidating — pulling back from its high, but in a controlled way. The pullback is getting shallower over time (the volatility is contracting), and volume is drying up (fewer shares trading). This is a VCP.

The idea is that the stock is "coiling" like a spring. The strong prior uptrend shows there's demand for the stock. The consolidation with contracting volatility and drying volume shows that sellers are exhausted. When the stock breaks out of this consolidation on high volume, it often runs to new highs.

#### How the Screen Works

For each stock, the screener checks five conditions:

1. **Prior advance** — the stock must have gained at least 30% (default) over the first 9 months of the 1-year window. This ensures we're looking at stocks that had a strong uptrend before the consolidation.

2. **Contraction** — the current pullback from the recent high must be no more than 50% (default). This ensures the consolidation isn't too deep — we're looking for shallow, controlled pullbacks, not crashes.

3. **Trend filter** — the stock must be trading above its 200-day moving average. This ensures we're only looking at stocks in a long-term uptrend.

4. **Volume dry-up** — the average volume over the last 10 days must be less than the average volume over the last 60 days. This shows that selling pressure is easing — fewer people are willing to sell at these prices.

5. **Tightening** — the volatility of daily returns over the last 10 days must be less than the volatility over the last 63 days (3 months). This shows that the price action is calming down — the stock is "coiling."

All five conditions must be met for a stock to be included in the results.

#### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Market data provider |
| `universe` | `str` | `"sp500"` | Universe to screen |
| `max_contraction_pct` | `float` | `0.50` | Maximum pullback from recent high (50%) |
| `min_prior_advance_pct` | `float` | `0.30` | Minimum prior uptrend (30%) |
| `limit` | `int` | `50` | Maximum number of results |

#### Returns

A table with one row per stock that shows a VCP pattern. Columns include: `symbol`, `price`, `prior_advance_pct`, `contraction_pct`, `volume_dryup_ratio`, `tightening_ratio`.

Results are sorted by `contraction_pct` (shallowest pullbacks first), on the theory that the tightest, most contracted bases are closest to breaking out.

#### Design Notes

- **Requires full year of data** — the VCP screen needs at least 200 bars of history to compute the 200-day moving average and assess the prior advance. Stocks with less than 200 days of history are silently skipped.

- **Not agent-tunable** — the agent tool exposes only `universe` and `limit`. The `max_contraction_pct` and `min_prior_advance_pct` thresholds are fixed at their defaults (50% and 30%) when called through the agent. If you want to adjust these thresholds, you need to call the Python function directly.

---

### screen_breakout_candidates

**Agent tool:** `screen_breakouts_tool`

This screen looks for stocks trading near their 52-week high on above-average volume — a classic momentum/breakout setup.

#### What Is a Breakout?

A breakout occurs when a stock's price moves above a resistance level (in this case, the 52-week high) on strong volume. The idea is that breaking above a significant high on high volume shows strong buying interest and often leads to further upside.

This screen looks for stocks that are *near* their 52-week high (within 5% by default) and showing volume expansion (at least 1.5x the 20-day average volume by default). These are stocks that are poised to break out or have just broken out.

#### How the Screen Works

For each stock, the screener checks two conditions:

1. **Near high** — the stock's current price must be within 5% (default) of its 52-week high. This ensures we're looking at stocks that are strong, not stocks that have fallen significantly from their highs.

2. **Volume surge** — today's volume must be at least 1.5x (default) the 20-day average volume. This shows that there's unusual buying interest — more people than normal are trading the stock.

Both conditions must be met. Results are sorted by volume ratio (highest first), on the theory that the strongest volume confirmation is the most decisive breakout signal.

#### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Market data provider |
| `universe` | `str` | `"sp500"` | Universe to screen |
| `proximity_to_high_pct` | `float` | `0.05` | Maximum distance below 52-week high (5%) |
| `volume_ratio_min` | `float` | `1.5` | Minimum volume vs. 20-day average (1.5x) |
| `limit` | `int` | `50` | Maximum number of results |

#### Returns

A table with one row per stock that meets the criteria. Columns include: `symbol`, `price`, `pct_from_high`, `volume_ratio`.

Results are sorted by `volume_ratio` (highest first).

---

### screen_oversold_reversal

**Agent tool:** `screen_oversold_tool`

This screen looks for stocks that have sold off sharply, are technically oversold, and are showing an early sign of reversal — a "buy the dip with confirmation" setup.

#### What Is an Oversold Reversal?

When a stock falls sharply, it can become "oversold" — meaning it has fallen too far, too fast, and is due for a bounce. Traders measure this using the RSI indicator — an RSI below 30 is considered oversold.

But buying every oversold stock is dangerous — some oversold stocks keep falling (catching a falling knife). This screen adds a confirmation step: it only includes stocks that are showing an early sign of reversal — a day where the price closes in the upper half of its range and is higher than the previous day's close.

This combination — oversold + sufficient decline + reversal confirmation — identifies stocks that have sold off but are showing early signs of bottoming.

#### How the Screen Works

For each stock, the screener checks three conditions:

1. **Oversold** — the stock's RSI (14-period) must be below 30 (default). This identifies stocks that have fallen sharply and are technically oversold.

2. **Sufficient decline** — the stock must have fallen at least 20% (default) from its 6-month high. This ensures we're looking at stocks that have actually sold off significantly, not just stocks with a low RSI due to normal volatility.

3. **Reversal bar** — the most recent day's price action must show a sign of reversal:
   - The day's close must be in the upper half of the day's range (close is above the midpoint of high and low)
   - The day's close must be higher than the previous day's close (an up day)

   This shows that buyers stepped in during the day and pushed the price up from the lows — an early sign that selling pressure is easing.

All three conditions must be met. Results are sorted by RSI (lowest first), so the most extremely oversold stocks appear at the top.

#### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Market data provider |
| `universe` | `str` | `"sp500"` | Universe to screen |
| `rsi_threshold` | `float` | `30.0` | Maximum RSI-14 (below this = oversold) |
| `min_decline_pct` | `float` | `0.20` | Minimum decline from 6-month high (20%) |
| `limit` | `int` | `50` | Maximum number of results |

#### Returns

A table with one row per stock that meets the criteria. Columns include: `symbol`, `price`, `rsi`, `decline_pct`.

Results are sorted by `rsi` (lowest first).

#### Design Notes

- **Reversal confirmation is key** — the reversal bar requirement is what separates this screen from a simple "buy every oversold stock" approach. By requiring the stock to show an actual sign of reversal (up day, close in upper half of range), we avoid catching stocks that are still in free fall.

- **Fast scan** — this screen only requires 30 bars of history (much less than VCP's 200), so it runs quickly even on large universes.

---

## What This Means for You

The screener tools give you the power to search hundreds or thousands of stocks in seconds, filtering down to the ones that match your specific criteria. Whether you're looking for cheap value stocks, strong momentum plays, specific chart patterns, or a combination of factors, the screener can find them.

But remember: a screen is just a starting point. It gives you a list of candidates, not a list of buys. You still need to do your own research — look at the company's business, understand why it passed the screen, check the overall market environment, and decide if it fits your investment strategy and risk tolerance.

The screens are also only as good as the criteria you specify. If you set your thresholds too tight, you might miss good opportunities. If you set them too loose, you'll get too many results to analyze. Experiment with different criteria to find what works for your investment approach.

Finally, be aware that screens are point-in-time snapshots. A stock that passes a momentum screen today might fail it tomorrow if the market reverses. Screens are tools to help you generate ideas, not set-and-forget recommendations. Use them as part of a broader investment process that includes ongoing monitoring and risk management.

# Portfolio Tools

`quantagent/tools/portfolio.py`

Tools for building and analyzing multi-stock portfolios. Whether you're managing a real portfolio or just exploring "what if I owned these 5 stocks together?", these tools help you answer three key questions:

1. **How should I allocate?** — What percentage of my money should go into each stock?
2. **How risky is it?** — What's the downside? How does it compare to the market?
3. **What could happen?** — What are the possible future outcomes?

All three tools work by downloading historical price data for your stocks, then running calculations on that data. They share a common helper that fetches prices for multiple stocks at once and cleans up any missing data.

---

## optimize_portfolio

**Agent tool:** `optimize_portfolio_tool`

Figures out the best way to split your money across a list of stocks based on historical performance.

### What It Does

Given a list of stocks (like AAPL, MSFT, GOOG), this tool calculates the optimal percentage to invest in each one. "Optimal" depends on what you're trying to achieve:

- **Maximum Sharpe ratio** — best risk-adjusted return (the default)
- **Minimum volatility** — lowest overall risk
- **Risk parity** — equal risk contribution from each stock
- **Equal weight** — same percentage in each stock (the simplest approach)

The tool looks at historical returns and how the stocks move together (correlation), then uses mathematical optimization to find the allocation that best meets your goal.

### How It Works

1. **Download price history** — fetches 2 years of daily prices for all your stocks
2. **Calculate returns** — converts prices to daily percentage changes
3. **Compute statistics** — calculates average returns and the covariance matrix (how stocks move together)
4. **Optimize** — uses the SLSQP algorithm to find the best weights
5. **Clean up** — removes any negative weights (no short selling) and normalizes so everything adds up to 100%

### The Four Methods

**Maximum Sharpe Ratio** finds the portfolio with the best return per unit of risk. It's the classic "efficient portfolio" from modern portfolio theory. The math:

```
maximize: (portfolio_return) / (portfolio_volatility)
subject to: weights sum to 1, all weights between 0 and 1
```

**Minimum Volatility** finds the portfolio with the lowest overall risk, regardless of return. Good if you're risk-averse.

**Risk Parity** allocates so each stock contributes equally to the portfolio's total risk. It uses a simplified formula based on each stock's individual volatility (ignoring correlations), which is fast but not perfectly precise.

**Equal Weight** just splits your money evenly across all stocks. Simple, diversification-friendly, and often hard to beat in practice.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `symbols` | `list[str]` | required | List of stock tickers (e.g. ["AAPL", "MSFT", "GOOG"]) |
| `method` | `str` | `"max_sharpe"` | Optimization method (see above) |
| `period` | `str` | `"2y"` | How much history to use for optimization |
| `constraints` | `dict \| None` | `None` | Optional weight bounds per stock (only for max_sharpe/min_vol) |

### Returns

A dictionary with:
- `weights` — the optimal allocation (e.g. {"AAPL": 0.4, "MSFT": 0.35, "GOOG": 0.25})
- `expected_return` — annualized expected return
- `volatility` — annualized volatility (risk)
- `sharpe_ratio` — risk-adjusted return
- `method` — which optimization method was used

All numbers are rounded to 4 decimal places.

### Usage

**Python API:**
```python
result = await optimize_portfolio(
    provider, 
    symbols=["AAPL", "MSFT", "GOOG"], 
    method="max_sharpe",
    period="2y"
)
```

**Agent tool:**
```
optimize_portfolio_tool(symbols="AAPL,MSFT,GOOG", method="max_sharpe")
```

The agent tool only exposes `symbols` and `method`. The `period` and `constraints` parameters are fixed at their defaults.

### Design Notes

**Why SLSQP?** The SLSQP (Sequential Least Squares Programming) algorithm is scipy's standard solver for optimization problems with constraints. It's fast, reliable, and handles the "weights must sum to 1" constraint naturally.

**What if optimization fails?** If the optimizer can't find a solution (rare, but possible with weird data), it falls back to equal weights rather than crashing. You'll still get a diversified portfolio, just not an "optimal" one.

**Why no short selling?** After optimization, any negative weights are clipped to zero. This enforces a long-only portfolio — you can only buy stocks, not bet against them. This matches how most individual investors operate.

**Requires at least 2 stocks.** You can't optimize a portfolio with just one stock — there's nothing to optimize! The tool will raise an error if you pass fewer than 2 symbols.

---

## compute_portfolio_metrics

**Agent tool:** `compute_portfolio_risk`

Calculates risk metrics for a portfolio with fixed weights, comparing it to a benchmark (usually SPY).

### What It Does

Given a specific allocation (like 40% AAPL, 30% MSFT, 30% GOOG), this tool tells you:

- **Beta** — how volatile is the portfolio compared to the market?
- **Value at Risk (VaR)** — what's the worst daily loss I should expect?
- **Conditional VaR (CVaR)** — if things go really bad, how bad will it get?
- **Tracking error** — how much does the portfolio deviate from the benchmark?
- **Information ratio** — am I being compensated for that deviation?

These metrics help you understand the risk profile of your portfolio and whether it's behaving the way you expect.

### How It Works

1. **Download prices** — fetches historical prices for all your stocks plus the benchmark (SPY by default)
2. **Calculate portfolio returns** — weights each stock's daily return by its allocation and sums them up
3. **Compute metrics** — runs the risk calculations on the portfolio's return series

### The Math

**Beta** measures how much the portfolio moves when the market moves. A beta of 1.0 means the portfolio moves in lockstep with the benchmark. Beta > 1.0 means it's more volatile, beta < 1.0 means it's less volatile.

```
beta = covariance(portfolio, benchmark) / variance(benchmark)
```

**Value at Risk (VaR)** answers: "What's the worst daily loss I should expect 95% (or 99%) of the time?" It's calculated as the 5th (or 1st) percentile of historical daily returns. For example, if VaR 95% is -0.02, it means on 95% of days, the portfolio lost no more than 2%.

**Conditional VaR (CVaR)** answers: "If I'm having a really bad day (worse than VaR), how bad will it get?" It's the average of all returns below the VaR threshold. CVaR gives you a sense of tail risk — what happens in the worst cases.

**Tracking Error** measures how much the portfolio's returns deviate from the benchmark. High tracking error means the portfolio is doing its own thing (which can be good or bad). Low tracking error means it's closely following the benchmark.

**Information Ratio** tells you whether the deviation from the benchmark is worth it. It's the average excess return (portfolio minus benchmark) divided by the tracking error. A higher information ratio means you're being compensated for the active risk you're taking.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `weights` | `dict[str, float]` | required | Stock allocations (e.g. {"AAPL": 0.4, "MSFT": 0.3, "GOOG": 0.3}) |
| `period` | `str` | `"1y"` | How much history to analyze |
| `benchmark` | `str` | `"SPY"` | Benchmark symbol for comparison |

### Returns

A dictionary with:
- `beta` — portfolio beta vs. benchmark
- `var_95` — 95% Value at Risk (daily)
- `var_99` — 99% Value at Risk (daily)
- `cvar_95` — 95% Conditional VaR (daily)
- `tracking_error` — annualized tracking error
- `information_ratio` — information ratio

All numbers are rounded to 4 decimal places.

### Usage

**Python API:**
```python
result = await compute_portfolio_metrics(
    provider,
    weights={"AAPL": 0.4, "MSFT": 0.3, "GOOG": 0.3},
    period="1y",
    benchmark="SPY"
)
```

**Agent tool:**
```
compute_portfolio_risk(symbols="AAPL,MSFT,GOOG", weights="0.4,0.3,0.3")
```

The agent tool takes symbols and weights as comma-separated strings. The benchmark and period are fixed at their defaults.

### Design Notes

**Weights don't need to sum to 1.** The tool uses your weights as-is. If they sum to 0.8, that's fine — it just means 20% is in cash (or unallocated). If they sum to 1.2, you're using leverage. The metrics will reflect whatever allocation you specify.

**Historical VaR, not parametric.** The tool uses the actual historical distribution of returns to calculate VaR, not a theoretical normal distribution. This is more robust to fat tails and skewness in real market data.

**Division-by-zero protection.** If the benchmark has zero variance (impossible in practice, but theoretically possible), beta returns 0.0 instead of crashing. Same for information ratio if tracking error is zero.

---

## monte_carlo_simulation

**Agent tool:** `run_monte_carlo`

Simulates thousands of possible future scenarios for your portfolio based on historical behavior.

### What It Does

Instead of giving you a single point estimate ("your portfolio will return 8% next year"), this tool generates a distribution of possible outcomes. It answers questions like:

- "What's the median outcome?"
- "What's the worst-case scenario (5th percentile)?"
- "What's the best-case scenario (95th percentile)?"
- "What's the probability of losing money?"

This gives you a much richer picture of risk and reward than a single number.

### How It Works

1. **Download price history** — fetches 2 years of daily prices
2. **Calculate statistics** — computes average daily returns and the covariance matrix
3. **Simulate paths** — generates 1,000 random future paths, each 252 days long (1 year), using the historical statistics
4. **Calculate outcomes** — for each path, computes the final portfolio value
5. **Summarize** — reports percentiles, probability of loss, and expected value

### The Math

The simulation uses a **multivariate normal distribution** to generate random daily returns. This preserves the historical correlations between stocks — if AAPL and MSFT tend to move together, the simulated paths will reflect that.

For each simulation:
1. Draw 252 days of random returns for each stock (jointly, preserving correlations)
2. Calculate the portfolio's daily return (weighted average of stock returns)
3. Compound the daily returns to get the final portfolio value

After running 1,000 simulations, you have 1,000 possible final values. The tool reports:
- **Percentiles** (5th, 25th, 50th, 75th, 95th) — the range of outcomes
- **Probability of loss** — what fraction of simulations ended below the starting value
- **Expected value** — the average final value across all simulations

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `weights` | `dict[str, float]` | required | Stock allocations |
| `horizon_days` | `int` | `252` | How many days to simulate (~1 year) |
| `n_simulations` | `int` | `1000` | How many random paths to generate |

### Returns

A dictionary with:
- `p5`, `p25`, `p50`, `p75`, `p95` — percentiles of final portfolio value (1.0 = no change)
- `prob_loss` — probability of ending below starting value
- `expected_value` — average final value

All numbers are rounded to 4 decimal places and expressed as multiples of the starting value (1.0 = breakeven).

### Usage

**Python API:**
```python
result = await monte_carlo_simulation(
    provider,
    weights={"AAPL": 0.4, "MSFT": 0.3, "GOOG": 0.3},
    horizon_days=252,
    n_simulations=1000
)
```

**Agent tool:**
```
run_monte_carlo(symbols="AAPL,MSFT,GOOG", weights="0.4,0.3,0.3")
```

The agent tool uses fixed defaults for `horizon_days` (252) and `n_simulations` (1000).

### Design Notes

**Parametric, not bootstrap.** The simulation draws from a fitted normal distribution rather than resampling historical returns. This is faster and smoother, but assumes returns are normally distributed — which they're not (real returns have fat tails). The tool acknowledges this limitation in its design.

**Fixed random seed.** The simulation uses a fixed seed (42), so you get the same results every time you run it with the same inputs. This makes the output deterministic and reproducible, which is important for testing and debugging.

**Compounding, not additive.** Each simulated path compounds daily returns multiplicatively (1.01 × 1.02 × 0.99 × ...), not additively. This captures the real effect of compounding — a 10% gain followed by a 10% loss doesn't get you back to where you started (you end up at 0.99, not 1.00).

**2-year history, regardless of horizon.** The tool always uses 2 years of history to estimate the statistics, even if you're simulating a different horizon. This provides a reasonable sample size while staying current.

---

## Summary

These three tools work together to give you a complete picture of portfolio construction and risk:

1. **optimize_portfolio** — "Here's the best way to allocate"
2. **compute_portfolio_metrics** — "Here's how risky that allocation is"
3. **monte_carlo_simulation** — "Here's what could happen in the future"

Use them in sequence: optimize to find a good allocation, compute metrics to understand the risk, then run a Monte Carlo simulation to see the range of possible outcomes. This gives you a data-driven foundation for portfolio decisions, rather than just guessing.

All three tools require historical price data, so they're only as good as the data you feed them. Garbage in, garbage out. But with reasonable inputs, they provide powerful insights into portfolio behavior.

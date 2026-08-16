# Backtesting Tools

`quantagent/tools/backtesting.py`

Tools for testing trading strategies against historical data. Before you risk real money on a strategy, you should test it against the past to see how it would have performed. That's what backtesting does — it simulates trading your strategy over historical data and reports the results.

These tools use [vectorbt](https://vectorbt.dev/), a high-performance backtesting library that can simulate thousands of trades in seconds. They handle all the complexity of trade simulation (entries, exits, commissions, stop-losses) so you can focus on the strategy logic.

---

## run_backtest

**Agent tool:** `run_backtest_tool`

Runs a single backtest of a trading strategy against a stock's historical data.

### What It Does

Takes a strategy (like "buy when the 50-day moving average crosses above the 200-day") and a stock (like AAPL), simulates trading that strategy over the past 5 years, and reports how it would have performed.

The tool answers questions like:
- What would my total return have been?
- What's the Sharpe ratio (risk-adjusted return)?
- What was the maximum drawdown (worst peak-to-trough decline)?
- How many trades would I have made?
- What was my win rate?

### How It Works

1. **Download price history** — fetches historical OHLCV data for the stock
2. **Generate signals** — converts the strategy into buy/sell signals for each day
3. **Simulate trades** — uses vectorbt to simulate the trades (entries, exits, commissions, stop-losses)
4. **Calculate metrics** — computes performance and risk metrics from the simulated equity curve
5. **Return results** — gives you a comprehensive report

### Available Strategies

The tool supports 6 built-in strategies:

| Strategy | Description |
|----------|-------------|
| `sma_crossover` | Buy when fast SMA crosses above slow SMA, sell when it crosses below |
| `ema_crossover` | Same as SMA crossover but with exponential moving averages |
| `rsi_mean_reversion` | Buy when RSI is oversold, sell when overbought |
| `macd_momentum` | Buy when MACD crosses above signal line, sell when it crosses below |
| `bollinger_breakout` | Buy when price breaks above upper Bollinger Band, sell when it breaks below lower band |
| `buy_and_hold` | Buy on day 1 and hold forever (baseline for comparison) |

Each strategy has tunable parameters (like the SMA periods or RSI thresholds), but the agent tool uses fixed defaults.

### The Math

The tool computes standard performance metrics:

**Return metrics:**
- `total_return` — cumulative return over the entire period
- `cagr` — Compound Annual Growth Rate (annualized return)

**Risk metrics:**
- `max_drawdown` — largest peak-to-trough decline (as a positive percentage)
- `max_drawdown_duration_days` — how long the worst drawdown lasted
- `annualized_volatility` — standard deviation of daily returns, annualized

**Risk-adjusted metrics:**
- `sharpe_ratio` — return per unit of risk (higher is better)
- `sortino_ratio` — like Sharpe but only penalizes downside volatility
- `calmar_ratio` — return divided by max drawdown

**Trade metrics:**
- `win_rate` — percentage of winning trades
- `profit_factor` — gross profits / gross losses
- `total_trades` — number of completed trades

All metrics are computed by vectorbt from the simulated equity curve and trade log.

### Parameters

The tool takes a `BacktestConfig` object with these fields:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `symbol` | `str` | required | Stock ticker to backtest |
| `strategy` | `str` | required | Strategy name (see table above) |
| `period` | `str` | `"5y"` | How much history to test (1y, 2y, 5y, 10y) |
| `initial_capital` | `float` | `100000` | Starting cash |
| `commission` | `float` | `0.001` | Commission per trade (0.001 = 0.1%) |
| `stop_loss_pct` | `float \| None` | `None` | Stop-loss percentage (e.g. 0.05 for 5%) |
| `take_profit_pct` | `float \| None` | `None` | Take-profit percentage |

### Returns

A frozen `BacktestResult` object with all the metrics listed above, plus:
- `equity_curve` — the portfolio value over time (as a pandas Series)
- `monthly_returns` — returns broken down by month
- `trade_log` — details of every trade (entry/exit dates, prices, P&L)

The agent tool formats this as a markdown table for easy reading.

### Usage

**Python API:**
```python
from quantagent.tools.backtesting import run_backtest, BacktestConfig

config = BacktestConfig(
    symbol="AAPL",
    strategy="sma_crossover",
    period="5y",
    initial_capital=100000,
    commission=0.001
)
result = await run_backtest(provider, config)
print(f"CAGR: {result.cagr:.2%}")
print(f"Sharpe: {result.sharpe_ratio:.2f}")
print(f"Max Drawdown: {result.max_drawdown:.2%}")
```

**Agent tool:**
```
run_backtest_tool(symbol="AAPL", strategy="sma_crossover", period="5y")
```

The agent tool returns a formatted markdown table with the key metrics.

### Design Notes

**Why vectorbt?** Writing a backtester from scratch is hard — you have to handle trade entries/exits, commissions, stop-losses, position sizing, drawdown tracking, and more. vectorbt does all of this in a highly optimized, vectorized way. It's fast, reliable, and well-tested.

**Minimum data requirement.** The tool requires at least 50 bars of data (about 2 months of daily data). Performance metrics on shorter histories are statistically meaningless, so the tool raises an error rather than returning unreliable results.

**Stop-loss/take-profit.** If you specify `stop_loss_pct` or `take_profit_pct`, vectorbt will automatically exit trades when those levels are hit. If they're `None`, no stops are applied. The tool converts `None` to `NaN` internally because that's how vectorbt represents "no stop."

**Frozen results.** The `BacktestResult` is a frozen Pydantic model — once it's created, you can't modify it. This prevents accidental tampering with the results, which is important when the agent is passing results around to different tools.

**Unused fields.** The `BacktestConfig` has `position_size` and `custom_signals` fields, but they're not currently used by the backtest logic. vectorbt always uses full-equity sizing. These fields are reserved for future functionality.

---

## run_walkforward

**Agent tool:** Not exposed to agent

Tests a strategy's robustness by running it across multiple non-overlapping time periods (folds).

### What It Does

Instead of testing a strategy on one big chunk of history (like 5 years), walk-forward analysis splits the history into several smaller chunks (folds) and tests the strategy on each one separately.

Why? Because a strategy might work great in one market environment (like a bull market) but fail in another (like a bear market). By testing across multiple folds, you get a better sense of whether the strategy is robust or just lucky.

### How It Works

1. **Split history into folds** — e.g. 5 years of data split into 5 folds of 1 year each
2. **For each fold:**
   - Split the fold into a training period (70% of the data) and a test period (30%)
   - If `param_grid` is provided, optimize the strategy's parameters on the training period
   - Run the strategy with those parameters on the test period
   - Record the results
3. **Return results** — one `BacktestResult` per fold

This gives you a more realistic picture of how the strategy would perform in live trading, where you're constantly adapting to new market conditions.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `config` | `BacktestConfig` | required | Strategy configuration (same as `run_backtest`) |
| `n_splits` | `int` | `5` | Number of folds |
| `train_ratio` | `float` | `0.7` | Fraction of each fold used for training |
| `param_grid` | `dict \| None` | `None` | Parameter grid for optimization (see below) |
| `metric` | `str` | `"sharpe_ratio"` | Metric to optimize (if `param_grid` is provided) |

### Returns

A list of `BacktestResult` objects, one per fold, in chronological order. Each result includes a `best_params` field showing the optimized parameters for that fold (if `param_grid` was provided).

### Usage

**Python API:**
```python
results = await run_walkforward(
    provider,
    config=BacktestConfig(symbol="AAPL", strategy="sma_crossover"),
    n_splits=5,
    train_ratio=0.7,
    param_grid={"fast": [10, 20, 50], "slow": [50, 100, 200]},
    metric="sharpe_ratio"
)
for i, result in enumerate(results):
    print(f"Fold {i+1}: CAGR={result.cagr:.2%}, best_params={result.best_params}")
```

### Design Notes

**Train/test split.** Each fold is split into a training period (for parameter optimization) and a test period (for out-of-sample testing). This prevents overfitting — you optimize on past data, then test on data the optimizer hasn't seen.

**Optional optimization.** If you provide a `param_grid`, the tool will optimize the strategy's parameters on each fold's training period. If you don't provide a grid, it just runs the strategy with its default parameters on each fold.

**No stop-loss/take-profit.** Unlike `run_backtest`, the walk-forward tool doesn't apply stop-loss or take-profit levels. This is a limitation of the current implementation.

**Minimum data requirement.** The tool requires at least 100 bars per fold, so `len(df) >= n_splits * 100`. If you don't have enough data, it will raise an error.

---

## optimize_parameters

**Agent tool:** Not exposed to agent

Finds the best parameter values for a strategy by testing every combination in a grid.

### What It Does

Strategies like `sma_crossover` have tunable parameters (like the fast and slow moving average periods). This tool tests every combination of parameters you specify and returns the one that performs best according to a chosen metric (like Sharpe ratio).

### How It Works

1. **Build parameter grid** — creates every combination of parameter values (Cartesian product)
2. **For each combination:**
   - Generate trading signals using those parameters
   - Simulate the trades
   - Calculate the chosen metric (e.g. Sharpe ratio)
3. **Return the best** — the parameter combination with the highest metric value

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `config` | `BacktestConfig` | required | Strategy configuration |
| `param_grid` | `dict` | required | Parameter names → lists of values to test |
| `metric` | `str` | `"sharpe_ratio"` | Metric to maximize |

### Returns

A dictionary with:
- `best_params` — the optimal parameter combination
- `best_{metric}` — the metric value for the best parameters
- `all_results` — results for every parameter combination

### Usage

**Python API:**
```python
result = await optimize_parameters(
    provider,
    config=BacktestConfig(symbol="AAPL", strategy="sma_crossover"),
    param_grid={"fast": [10, 20, 50], "slow": [50, 100, 200]},
    metric="sharpe_ratio"
)
print(f"Best params: {result['best_params']}")
print(f"Best Sharpe: {result['best_sharpe_ratio']:.2f}")
```

### Design Notes

**Grid search, not smart optimization.** The tool tests every combination in the grid (brute force), not a smarter algorithm like Bayesian optimization. This is simple and guarantees you find the best combination within the grid, but it can be slow for large grids.

**Strategy-specific parameters.** Each strategy reads different parameters from the `param_grid`. For example:
- `sma_crossover` and `ema_crossover` read `fast` and `slow`
- `rsi_mean_reversion` reads `length`, `oversold`, and `overbought`
- `buy_and_hold` doesn't read any parameters (every combination is identical)

If you pass parameters that the strategy doesn't use, they're silently ignored.

**Minimum data requirement.** Like `run_backtest`, this tool requires at least 50 bars of data.

---

## format_backtest_result

**Agent tool:** Not exposed (used internally by `run_backtest_tool`)

Converts a `BacktestResult` into a human-readable markdown table.

### What It Does

Takes the raw backtest results and formats them as a markdown table that's easy to read in chat or agent output.

### How It Works

Creates a markdown header with the symbol, strategy, and period, then a table with rows for each metric:
- CAGR, Sharpe Ratio, Sortino Ratio, Calmar Ratio
- Max Drawdown, Max Drawdown Duration
- Win Rate, Total Trades, Profit Factor
- Total Return, Annualized Volatility
- Best Params (if available, from walk-forward optimization)

Percentages are formatted as `XX.XX%`, ratios as `X.XX`.

### Parameters

| Name | Type | Description |
|------|------|-------------|
| `result` | `BacktestResult` | The backtest results to format |

### Returns

A markdown string.

### Usage

**Python API:**
```python
markdown = format_backtest_result(result)
print(markdown)
```

### Design Notes

**Not all fields are included.** The formatted output doesn't include `equity_curve`, `monthly_returns`, or `trade_log` — those are only available on the raw `BacktestResult` object. The formatted output focuses on the key summary metrics.

**Conditional Best Params row.** If `result.best_params` is not `None` (i.e. the backtest was part of a walk-forward optimization), the output includes a "Best Params" row showing the optimized parameters.

---

## Summary

These backtesting tools let you test trading strategies against historical data before risking real money:

- **run_backtest** — test a strategy on one chunk of history
- **run_walkforward** — test a strategy across multiple time periods for robustness
- **optimize_parameters** — find the best parameter values for a strategy
- **format_backtest_result** — format results for easy reading

Use them in sequence:
1. Start with `run_backtest` to see if a strategy works at all
2. Use `optimize_parameters` to find the best parameter values
3. Use `run_walkforward` to test if the strategy is robust across different market environments

Remember: past performance doesn't guarantee future results. A strategy that worked great in the past might not work in the future. But backtesting gives you a data-driven starting point, which is better than guessing.

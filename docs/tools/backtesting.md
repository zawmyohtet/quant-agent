# Backtesting Tools

`quantagent/tools/backtesting.py` provides vectorized strategy backtesting on top of [vectorbt](https://vectorbt.dev/): a single-run backtest (`run_backtest`), a walk-forward evaluator (`run_walkforward`), a brute-force parameter grid search (`optimize_parameters`), and a markdown formatter for results (`format_backtest_result`). All three data-fetching functions pull OHLCV bars through an `AbstractDataProvider`, turn them into buy/sell signals via `quantagent.tools.technical.generate_signals`, and hand the price series and signals to `vbt.Portfolio.from_signals`, which does the actual trade simulation (fills, commissions, stop-loss/take-profit exits, equity accounting). Only `run_backtest` is currently wired up as an agent-callable tool.

## run_backtest

**Agent-facing tool name:** `run_backtest_tool`

**Purpose:** Runs a single historical backtest of one named strategy against one symbol and reports standard performance/risk metrics (CAGR, Sharpe, Sortino, Calmar, drawdown, win rate, profit factor) so a trader can judge whether a strategy would have worked historically before risking capital on it.

**Why built this way:**
- Uses `vbt.Portfolio.from_signals` instead of a hand-rolled bar-by-bar loop because vectorbt vectorizes the entire simulation (entries/exits, commission deduction, stop-loss/take-profit exits, trade and drawdown accounting) in one call — it is fast, well-tested, and avoids re-implementing fragile trade-lifecycle bookkeeping.
- Raises `ValueError` early if fewer than 50 bars are available (`len(df) < 50`), since performance ratios computed on very short histories are statistically meaningless.
- `stop_loss_pct` / `take_profit_pct` are converted to `np.nan` when unset (`config.stop_loss_pct if ... else np.nan`) because vectorbt's `sl_stop`/`tp_stop` parameters treat `NaN` as "no stop configured" rather than a valid distance.
- `BacktestResult` is a **frozen** (`ConfigDict(frozen=True)`) pydantic model — once a backtest completes, its metrics cannot be mutated in place, which matters for an agent that may hand the same result to multiple downstream consumers (report generation, chat formatting) without risking accidental tampering.
- All numeric fields are rounded to 4 decimal places at construction time, giving stable, deterministic string output regardless of floating-point noise from the underlying computation.
- **Caveat found in code:** `BacktestConfig.position_size` and `BacktestConfig.custom_signals` are declared fields but are never read anywhere in `run_backtest` (or `run_walkforward`/`optimize_parameters`) — they currently have no effect on the simulation. `vbt.Portfolio.from_signals` is always called with full-equity sizing; these fields appear to be reserved for future functionality.

**Math:**
- `total_return = pf.total_return()` — vectorbt's cumulative return over the whole equity curve: `final_portfolio_value / initial_cash - 1`.
- `n_years = len(pf.returns()) / 252` (252 = assumed trading days per year).
- `cagr = (1 + total_return) ** (1 / n_years) - 1` if `n_years > 0`, else `0.0`.
- `sharpe_ratio = pf.sharpe_ratio()` — vectorbt's annualized Sharpe ratio computed from daily returns with `freq="1d"` (annualization factor 252) and an implicit risk-free rate of 0 (vectorbt default): `mean(daily_returns) / std(daily_returns) * sqrt(252)`.
- `sortino_ratio = pf.sortino_ratio()` — same annualization (×√252) but the denominator is the downside deviation (standard deviation computed only over returns below the target, 0 by default) instead of the full standard deviation.
- `calmar_ratio = pf.calmar_ratio()` — annualized return divided by the absolute value of maximum drawdown.
- `max_drawdown = abs(pf.max_drawdown())` — largest peak-to-trough percentage decline in the equity curve, reported as a positive fraction.
- `max_drawdown_duration_days = pf.drawdowns.max_duration()` — longest duration (in days, since `freq="1d"`) of any single drawdown episode; converted from a `Timedelta` to `int` days if needed.
- `win_rate = pf.trades.win_rate()` — winning closed trades ÷ total closed trades.
- `profit_factor = pf.trades.profit_factor()` — sum of gross winning trade P&L ÷ sum of gross losing trade P&L (absolute value).
- `annualized_volatility = pf.annualized_volatility()` — `std(daily_returns) * sqrt(252)`.
- `monthly_returns` — daily returns resampled to month-end (`"ME"`) and compounded per month: `(1 + r).prod() - 1`.
- `equity_curve = pf.value()` — the portfolio's mark-to-market value time series.
- `trade_log = pf.trades.records_readable` if `pf.trades.count() > 0`, else an empty `DataFrame`.

**Usage:**

Input is a `BacktestConfig`:

| Field | Type | Default | Notes |
|---|---|---|---|
| `symbol` | `str` | required | Ticker to backtest. |
| `strategy` | `str` | required | One of `sma_crossover`, `ema_crossover`, `rsi_mean_reversion`, `macd_momentum`, `bollinger_breakout`, `buy_and_hold` (per `generate_signals`'s strategy dispatch). |
| `period` | `str` | `"5y"` | History window fetched from the provider (agent docstring suggests `1y`, `2y`, `5y`, `10y`). |
| `initial_capital` | `float` | `100_000.0` | Starting cash for the simulation. |
| `commission` | `float` | `0.001` | Passed to vectorbt as `fees` (fraction per trade, e.g. 0.001 = 10 bps). |
| `position_size` | `float` | `1.0` | **Currently unused** by the backtest logic (see caveat above). |
| `stop_loss_pct` / `take_profit_pct` | `float \| None` | `None` | Passed to vectorbt as `sl_stop`/`tp_stop`; `None` → `np.nan` (no stop). |
| `custom_signals` | `pd.Series \| None` | `None` | **Currently unused** by the backtest logic. |

Returns a frozen `BacktestResult`:

`symbol`, `strategy`, `period`, `cagr`, `sharpe_ratio`, `sortino_ratio`, `calmar_ratio`, `max_drawdown`, `max_drawdown_duration_days` (int), `win_rate`, `total_trades` (int), `profit_factor`, `total_return`, `annualized_volatility`, `equity_curve` (`pd.Series`), `monthly_returns` (`pd.Series`), `trade_log` (`pd.DataFrame`), `best_params` (`dict[str, float] | None`, defaults to `None`). `run_backtest` never populates `best_params` — it's only set by `run_walkforward` when a fold was grid-searched (see below).

The agent-facing wrapper `run_backtest_tool(symbol, strategy, period="5y")` builds a `BacktestConfig` (uppercasing the symbol), runs `run_backtest`, and returns `format_backtest_result(result)` — a markdown string, not the raw model.

Example agent call:
```
run_backtest_tool(symbol="AAPL", strategy="sma_crossover", period="5y")
```

## run_walkforward

**Agent-facing tool name:** Not exposed as an agent tool.

**Purpose:** Intended to validate a strategy's robustness by evaluating it across several non-overlapping historical windows (folds) instead of one full-history backtest, so that performance metrics reflect multiple independent market regimes rather than a single lucky/unlucky period.

**Why built this way:** Each fold is split into a train slice and a test slice
(`train_end = int(len(split_df) * train_ratio)`). When an optional `param_grid` is supplied, the
train slice is grid-searched (via `_grid_search`, the same core loop `optimize_parameters` uses,
factored out so it can run against an in-memory DataFrame instead of fetching its own) and the
winning parameters are used to generate the test slice's signals — a real train/test split, not
just "backtest the same strategy on N sequential slices of history." When `param_grid` is omitted
(the default), each fold still runs `config.strategy` with its hardcoded defaults, and
`best_params` stays `None` on the result — preserving the original, simpler behavior for callers
that don't need per-fold optimization. Unlike `run_backtest`, the vectorbt call inside
`run_walkforward` does not pass `sl_stop`/`tp_stop`, so stop-loss/take-profit from the config are
not applied in walk-forward runs. Guards against too little data with `len(df) < n_splits * 100`
(at least 100 bars per fold).

**Math:**
- `split_size = len(df) // n_splits` (integer division — any remainder bars beyond `n_splits * split_size` are simply not included in any fold).
- For fold `i`: `start_idx = i * split_size`, `end_idx = start_idx + split_size`, `split_df = df.iloc[start_idx:end_idx]`.
- `train_end = int(len(split_df) * train_ratio)`; `test_df = split_df.iloc[train_end:]` is always used for the reported metrics. When `param_grid` is given, `train_df = split_df.iloc[:train_end]` is fed to `_grid_search` (same Cartesian-product grid search described in `optimize_parameters` below) to obtain that fold's `best_params`.
- Each fold runs `vbt.Portfolio.from_signals(test_signals["Close"], entries, exits, freq="1d", init_cash=config.initial_capital, fees=config.commission)` and is converted to a `BacktestResult` via the same `_portfolio_to_result` helper used by `run_backtest` (same Sharpe/Sortino/Calmar/drawdown formulas described above), with `best_params` attached (or `None` if no grid search ran).

**Usage:**
```python
run_walkforward(
    provider, config: BacktestConfig, n_splits: int = 5, train_ratio: float = 0.7,
    param_grid: dict | None = None, metric: str = "sharpe_ratio",
) -> list[BacktestResult]
```
- `n_splits`: number of sequential folds to split history into.
- `train_ratio`: fraction of each fold reserved as "train".
- `param_grid`: optional dict of parameter name → list of candidate values (same shape as `optimize_parameters`'s `param_grid`). When given, each fold's train slice is grid-searched and the winning params generate that fold's test signals; when `None`, no optimization happens.
- `metric`: vectorbt `Portfolio` metric method to maximize during per-fold optimization; ignored when `param_grid` is `None`.
- Returns a `list[BacktestResult]`, one per fold, in chronological order; each fold's `best_params` is populated only when `param_grid` was supplied.
- Not reachable from the agent's tool list; must be called directly from Python.

## optimize_parameters

**Agent-facing tool name:** Not exposed as an agent tool.

**Purpose:** Intended to grid-search a strategy's parameters (e.g. moving-average lengths) to find the combination that maximizes a chosen vectorbt performance metric.

**Why built this way:** Grid search (exhaustive `itertools.product` over parameter values) is used
instead of a smarter optimizer (e.g. Bayesian optimization) presumably for simplicity and
guaranteed global coverage of a small discrete grid, with per-combo failures caught and logged
rather than aborting the whole search (`_evaluate_combo` returns `None` on exception,
`_grid_search` skips it). The core loop is factored out into a synchronous helper, `_grid_search(df,
config, param_grid, metric) -> dict`, that runs directly against an in-memory DataFrame;
`optimize_parameters` itself is now a thin wrapper that fetches `df` from the provider, validates
its length, and delegates to `_grid_search` — this split is what lets `run_walkforward` reuse the
exact same grid-search logic against each fold's in-memory train slice (see above) without
re-fetching data per fold. `_evaluate_combo` passes each combo's `params` dict straight into
`generate_signals(df, config.strategy, params)`, so the sampled parameters do reach the strategy
functions in `quantagent/tools/technical.py`, each of which reads its own tunable keys out of
`params` (e.g. `_signal_sma_crossover` reads `fast`/`slow`, falling back to its original
`50`/`200` defaults if a key is absent).

**Math:**
- Builds the Cartesian product of all `param_grid` value lists via `itertools.product(*values)`, zipping each combination back onto `param_grid`'s keys to form a `params` dict per combo.
- For each combo, runs `vbt.Portfolio.from_signals(signals_df["Close"], entries, exits, freq="1d", init_cash=config.initial_capital, fees=config.commission)` (no stop-loss/take-profit applied here either).
- `metric_value = float(getattr(pf, metric)())` — dynamically invokes the named zero-argument vectorbt `Portfolio` method (e.g. `pf.sharpe_ratio()`, `pf.total_return()`), so `metric` must be a valid vectorbt Portfolio metric method name.
- Tracks the running maximum: starts at `best_value = -np.inf`; any combo with `metric_value > best_value` becomes the new best.
- Requires `len(df) >= 50` bars, else raises `ValueError`.

**Usage:**
```python
optimize_parameters(
    provider, config: BacktestConfig, param_grid: dict, metric: str = "sharpe_ratio"
) -> dict
```
- `param_grid`: dict of parameter name → list of candidate values, e.g. `{"fast": [10, 20, 50], "slow": [50, 100, 200]}`. Only the keys each strategy's handler actually reads have an effect (e.g. `sma_crossover`/`ema_crossover` read `fast`/`slow`; `rsi_mean_reversion` reads `length`/`oversold`/`overbought`; `buy_and_hold` reads nothing, so every combo is identical for that strategy — this is expected, not a bug).
- `metric`: name of a vectorbt `Portfolio` metric method to maximize (default `"sharpe_ratio"`; e.g. `"total_return"` also valid).
- Returns: `{"best_params": dict, f"best_{metric}": float, "all_results": [{"params": dict, metric: float}, ...]}`.
- Not reachable from the agent's tool list; must be called directly from Python.

## format_backtest_result

**Agent-facing tool name:** Not exposed as its own agent tool — used internally by `run_backtest_tool` to convert its `BacktestResult` into the string returned to the LLM.

**Purpose:** Renders a `BacktestResult` as a human-readable markdown table for display in chat/agent output.

**Why built this way:** Agent tools must return text, not pydantic objects, so formatting is split out as a separate pure function — keeping `run_backtest`'s numeric computation testable independently of presentation. Percentage fields are formatted with `.2%` and ratio fields with `.2f` for readability.

**Math:** None — pure string formatting, no computation.

**Usage:**
```python
format_backtest_result(result: BacktestResult) -> str
```
Produces a markdown header (`## Backtest: {symbol} ({strategy})`, period line) followed by a table with rows: CAGR, Sharpe Ratio, Sortino Ratio, Calmar Ratio, Max Drawdown, Max Drawdown Duration, Win Rate, Total Trades, Profit Factor, Total Return, Annualized Volatility, plus a conditional **Best Params** row appended only when `result.best_params is not None` (i.e. only for walk-forward folds that were grid-searched). Note that `equity_curve`, `monthly_returns`, and `trade_log` are **not** included in this formatted summary — only available on the raw `BacktestResult`.

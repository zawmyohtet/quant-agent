# Portfolio Tools

`quantagent/tools/portfolio.py` provides multi-asset portfolio analytics on top of daily close prices fetched via `AbstractDataProvider.get_batch_ohlcv`: weight optimization across four objectives (`optimize_portfolio`), risk-metric computation relative to a benchmark (`compute_portfolio_metrics`), and a parametric Monte Carlo forward-return simulation (`monte_carlo_simulation`). All three functions share the private `_fetch_prices` helper, which batch-fetches close prices for a symbol list and drops any rows with missing data across the joined price panel. All three are exposed as agent tools (with somewhat narrower parameter surfaces than their underlying Python functions).

## optimize_portfolio

**Agent-facing tool name:** `optimize_portfolio_tool`

**Purpose:** Computes a set of portfolio weights across a list of symbols under one of four allocation objectives (maximum Sharpe ratio, minimum volatility, risk parity, or equal weight), giving a trader a data-driven starting allocation derived from historical returns and covariance.

**Why built this way:**
- `max_sharpe` and `min_vol` are solved with `scipy.optimize.minimize(method="SLSQP")` — Sequential Least Squares Programming is scipy's standard solver for smooth, constrained nonlinear problems with an equality constraint (weights sum to 1) and box bounds, avoiding a hand-rolled gradient-descent implementation.
- `risk_parity` uses a closed-form inverse-variance formula rather than an iterative risk-contribution solver — much cheaper and always converges, at the cost of being an approximation: it equalizes weights by *marginal variance only* and ignores cross-asset covariance, so it only achieves true equal risk *contribution* when assets are uncorrelated.
- `equal_weight` is a trivial `1/n` baseline used as both a sensible default output and the optimizer's starting point (`np.ones(n) / n`) for the SLSQP-based methods.
- If SLSQP fails to converge (`result.success` is `False`), the optimizer silently falls back to equal weights rather than raising — keeps the tool robust to solver failures in an agent context, at the cost of masking optimizer failures from the caller.
- After the method-specific weights are produced, **all four methods** go through the same post-processing: negative weights are clipped to zero (`np.maximum(weights, 0)`) and the result is renormalized to sum to 1. This enforces a long-only portfolio defensively, even though SLSQP's own bounds already default to `[0, 1]`.
- Requires at least 2 symbols with overlapping non-NaN return data (`len(returns.columns) < 2` raises `ValueError`).

**Math:**
- `returns = prices.pct_change().dropna()` — simple daily percentage returns.
- `mean_returns = returns.mean() * 252` — annualized mean return (252 trading days/year).
- `cov_matrix = returns.cov() * 252` — annualized covariance matrix Σ.
- Reported portfolio expected return: `port_return = w · mean_returns`.
- Reported portfolio volatility: `port_vol = sqrt(wᵀ Σ w)`.
- Reported portfolio Sharpe: `sharpe = port_return / port_vol` (assumes risk-free rate = 0), or `0.0` if `port_vol == 0`.

Per-objective formulation:

| Objective | Formulation |
|---|---|
| `max_sharpe` | `minimize_w  −(w·μ) / sqrt(wᵀ Σ w)`  s.t. `Σw = 1`, `0 ≤ wᵢ ≤ 1` (or caller-supplied `constraints["bounds"]`). Solved via SLSQP starting from `w₀ = 1/n`. Risk-free rate assumed 0 (explicit code comment). |
| `min_vol` | `minimize_w  sqrt(wᵀ Σ w)`  s.t. `Σw = 1`, same bounds. Solved via SLSQP starting from `w₀ = 1/n`. |
| `risk_parity` | `wᵢ = (1/Σᵢᵢ) / Σⱼ(1/Σⱼⱼ)` — inverse of each asset's own variance (diagonal of Σ only), normalized to sum to 1. Ignores off-diagonal covariance/correlation. |
| `equal_weight` | `wᵢ = 1/n` for all `n` assets. |

Final step for every method: `w = max(w, 0)` elementwise, then `w = w / Σw`.

**Usage:**
```python
optimize_portfolio(
    provider, symbols: list[str], method: str = "max_sharpe",
    period: str = "2y", constraints: dict | None = None,
) -> dict
```
- `method`: one of `max_sharpe`, `min_vol`, `risk_parity`, `equal_weight` (else `ValueError: Unknown optimization method`).
- `period`: history window for estimating mean/covariance, default `"2y"`.
- `constraints`: optional dict; only recognized key is `"bounds"` — a list of `(low, high)` tuples, one per asset, passed to SLSQP's `bounds` (used only by `max_sharpe`/`min_vol`; ignored by `risk_parity`/`equal_weight`).
- Returns: `{"weights": {symbol: weight, ...}, "expected_return": float, "volatility": float, "sharpe_ratio": float, "method": str}`, all floats rounded to 4 decimal places.

The agent-facing wrapper `optimize_portfolio_tool(symbols, method="max_sharpe")` only exposes `symbols` (comma-separated string, split/stripped/uppercased) and `method`; `period` and `constraints` are not agent-tunable and always use their defaults (`"2y"`, `None`).

Example agent call:
```
optimize_portfolio_tool(symbols="AAPL,MSFT,GOOG", method="max_sharpe")
```

## compute_portfolio_metrics

**Agent-facing tool name:** `compute_portfolio_risk`

**Purpose:** Given a fixed set of portfolio weights, computes standard risk metrics — beta versus a benchmark, historical Value-at-Risk and Conditional VaR, tracking error, and information ratio — so a trader can understand a specific allocation's downside risk and benchmark-relative behavior.

**Why built this way:**
- Fetches all portfolio symbols plus the benchmark symbol in a single batched `get_batch_ohlcv` call for efficiency, rather than one request per symbol.
- Portfolio returns are computed as the weighted sum of constituent daily returns, using the caller-supplied weights directly (`port_returns += returns[sym] * w`) — weights are **not** renormalized, so caller-supplied weights that don't sum to 1 will directly bias every downstream metric.
- VaR/CVaR use the empirical/historical percentile method (`np.percentile` on the realized daily return series) rather than a parametric (e.g. Gaussian) assumption — simple and robust to non-normal, skewed, or fat-tailed return distributions, at the cost of being sample-size dependent (default `period="1y"` gives only ~252 daily observations).
- Division-by-zero guards: `beta` returns `0.0` if benchmark variance is 0; `information_ratio` returns `0.0` if `tracking_error` is 0 — avoids `NaN`/`inf` propagating to the agent's output.
- Requires non-empty joined return data (`returns.empty` raises `ValueError`).

**Math:**
- `port_returns = Σᵢ (returnsᵢ × weightᵢ)` over the symbols present in `weights` and in the fetched return data (benchmark excluded from this sum).
- `bench_returns = returns[benchmark]` (or an all-zero series if the benchmark wasn't fetched).
- **Beta:** `cov(port_returns, bench_returns) / var(bench_returns)`, computed via `np.cov(port, bench)[0, 1] / np.cov(port, bench)[1, 1]` — the classical CAPM beta, using population covariance.
- **VaR 95%:** `np.percentile(port_returns, 5)` — the daily return below which only 5% of historical daily returns fall (a raw, non-annualized daily return figure, typically negative).
- **VaR 99%:** `np.percentile(port_returns, 1)`.
- **CVaR 95% (Expected Shortfall):** mean of all daily returns `≤ var_95`; `0.0` if no returns fall at/below the VaR threshold.
- **Tracking error:** `std(active_returns) × sqrt(252)`, where `active_returns = port_returns − bench_returns` — annualized standard deviation of the return differential vs. benchmark.
- **Information ratio:** `mean(active_returns) × 252 / tracking_error` — annualized average active return divided by annualized tracking error.

**Usage:**
```python
compute_portfolio_metrics(
    provider, weights: dict[str, float], period: str = "1y", benchmark: str = "SPY",
) -> dict
```
- `weights`: mapping of symbol → portfolio weight (not required to sum to 1; used as-is).
- `period`: history window, default `"1y"`.
- `benchmark`: symbol to compare against, default `"SPY"`.
- Returns: `{"beta": float, "var_95": float, "var_99": float, "cvar_95": float, "tracking_error": float, "information_ratio": float}`, all rounded to 4 decimal places.

The agent-facing wrapper `compute_portfolio_risk(symbols, weights)` takes comma-separated symbols and comma-separated weights, parsed via the shared `_parse_symbols_and_weights` helper in `tools_registry.py` — a mismatched-length pair **raises a `ValueError`** naming both counts rather than silently truncating to the shorter list. `benchmark` (fixed to `"SPY"`) and `period` (fixed to `"1y"`) are not agent-tunable.

Example agent call:
```
compute_portfolio_risk(symbols="AAPL,MSFT,GOOG", weights="0.4,0.3,0.3")
```

## monte_carlo_simulation

**Agent-facing tool name:** `run_monte_carlo`

**Purpose:** Simulates a distribution of possible future portfolio outcomes over a chosen horizon by sampling from the historical joint return distribution, giving a trader a probabilistic view (percentile outcomes, probability of loss, expected value) rather than a single deterministic forecast.

**Why built this way:**
- Uses a **parametric** simulation — draws are sampled from a multivariate normal distribution fit to historical daily mean returns and covariance (`rng.multivariate_normal`) — rather than bootstrapping historical return rows directly. This is simple and fast via numpy, but inherits the Gaussian assumption's known weakness of underestimating tail risk, skew, and fat tails present in real asset returns.
- Uses a **fixed random seed** (`np.random.default_rng(42)`), making simulation output fully deterministic and reproducible across calls — the same portfolio and parameters always yield the same reported percentiles rather than results that vary run to run.
- History window for estimating the mean/covariance inputs is hardcoded to `"2y"` regardless of `horizon_days`, independent of any period parameter used elsewhere in the module.
- Simulates full daily paths (`horizon_days` steps per simulation) and compounds them multiplicatively (`np.cumprod(1 + returns)`) rather than sampling a single aggregate horizon return directly — captures multiplicative compounding effects (as opposed to a single-shot additive-return draw), at the cost of `horizon_days × n_simulations` normal draws (default 252 × 1000 = 252,000 draws per asset).
- Requires non-empty return data (`returns.empty` raises `ValueError`).

**Math:**
- `mean_returns = returns.mean()` — per-asset **daily** mean return (not annualized; used directly as the per-step mean for the daily simulation).
- `cov_matrix = returns.cov()` — per-asset **daily** covariance matrix (not annualized).
- `w` — weight vector aligned to `symbols`, with `0.0` for any symbol absent from the `weights` dict.
- `simulated = rng.multivariate_normal(mean_returns, cov_matrix, size=(n_simulations, horizon_days))` — draws `n_simulations` independent paths, each `horizon_days` long, of jointly-correlated daily asset returns (correlation preserved across assets within a day; days are i.i.d.).
- `port_simulated[s, t] = simulated[s, t, :] · w` — daily portfolio return for simulation `s`, day `t`.
- `cumulative[s, t] = Π_{k=0}^{t} (1 + port_simulated[s, k])` — cumulative growth factor (starting portfolio value = 1.0) through day `t` for simulation `s`.
- `final_values = cumulative[:, -1]` — ending value multiple (1.0 = breakeven) for each of the `n_simulations` paths after `horizon_days`.
- `p5, p25, p50, p75, p95` — percentiles of `final_values` across all simulated paths (`np.percentile`).
- `prob_loss = mean(final_values < 1.0)` — fraction of simulated paths ending below the starting value.
- `expected_value = mean(final_values)` — average ending value multiple across all simulations.

**Usage:**
```python
monte_carlo_simulation(
    provider, weights: dict[str, float], horizon_days: int = 252, n_simulations: int = 1000,
) -> dict
```
- `weights`: mapping of symbol → portfolio weight.
- `horizon_days`: number of simulated daily steps, default `252` (~1 trading year).
- `n_simulations`: number of independent simulated paths, default `1000`.
- Returns: `{"p5": float, "p25": float, "p50": float, "p75": float, "p95": float, "prob_loss": float, "expected_value": float}`, all rounded to 4 decimal places and expressed as multiples of starting portfolio value (`1.0` = no change).

The agent-facing wrapper `run_monte_carlo(symbols, weights)` takes comma-separated symbols and weights, parsed via the same `_parse_symbols_and_weights` helper as `compute_portfolio_risk` (mismatched lengths raise a `ValueError` instead of silently truncating). `horizon_days` and `n_simulations` are **not** agent-tunable and always use their defaults (252, 1000).

Example agent call:
```
run_monte_carlo(symbols="AAPL,MSFT,GOOG", weights="0.4,0.3,0.3")
```

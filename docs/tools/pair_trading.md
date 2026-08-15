# pair_trading.py

Pair trading / statistical arbitrage: finds cointegrated pairs (Engle-Granger)
within a universe or sector, and computes tradeable spread metrics — OLS hedge
ratio, spread z-score, and mean-reversion half-life. Correlation is used only
as a cheap pre-filter; cointegration, not correlation, is what makes a spread
tradeable. Source: `quantagent/tools/pair_trading.py`.

## find_cointegrated_pairs

**Agent-facing tool name:** `find_cointegrated_pairs`

**Purpose:** Scans every pair of symbols within a universe (optionally
restricted to one sector) and returns the pairs that pass a correlation
pre-filter *and* a statistical cointegration test, ranked by cointegration
strength — i.e. candidate pairs for a stat-arb spread trade.

**Why built this way:**

- **Two-stage filter for cost control.** Correlation (`matrix.corr()`, a
  single vectorized O(n²) matrix op) is applied first because it's cheap;
  the Engle-Granger test (`statsmodels.tsa.stattools.coint`, an OLS
  regression plus an ADF-style test on residuals per pair) is applied only to
  pairs that survive the correlation gate, since it's the expensive step.
- **Correlation ≠ cointegration**, called out explicitly in the module
  docstring: two series can be highly correlated moment-to-moment without
  ever mean-reverting to a stable spread, and vice versa. The correlation
  gate (`min_correlation`, default `0.7`) is only a coarse pre-filter, not a
  substitute for the cointegration test.
- **Sector restriction is recommended** (docstring: "cross-sector pairs
  cointegrate by accident far more often than by economics") — a spurious
  cointegration result between economically unrelated names is far more
  likely than a true, tradeable long-run relationship.
- **`_MIN_OBSERVATIONS = 120`** aligned daily sessions per symbol are
  required before a symbol enters the close matrix (`_close_matrix`),
  guarding against unstable OLS/AR(1) estimates on short series.
- **`max_symbols` cap (default 60)** exists because pair count grows
  quadratically — at 60 symbols that's already `60*59/2 = 1770` pairs
  tested per scan.
- **`asyncio.to_thread`** runs the CPU-bound `_scan_pairs` loop off the
  event loop so it doesn't block concurrent I/O elsewhere in the agent.
- Sector classification lookups are cached (via `classify_symbols` /
  `DataCache`) so repeated sector-filtered scans don't re-hit the provider.

**Math:**

For each pair `(a, b)` of columns in the aligned close-price matrix:

1. **Correlation gate:** skip the pair unless
   `corr(a, b) >= min_correlation` (default `0.7`), computed once via
   `matrix.corr()`.
2. **Hedge ratio (OLS):**
   `beta = polyfit(b, a, deg=1)[0]` — the slope of a degree-1 least-squares
   fit of `a` on `b`, i.e. the OLS regression coefficient in
   `a_t = alpha + beta * b_t + eps_t`. `beta` is the hedge ratio (units of
   `b` per unit of `a`'s spread).
3. **Spread:** `spread_t = a_t - beta * b_t`.
4. **Engle-Granger cointegration test:**
   `statsmodels.tsa.stattools.coint(a, b) -> (statistic, pvalue, crit_values)`.
   This runs the two-step Engle-Granger procedure: regress one series on the
   other, then run an augmented Dickey-Fuller-style test for a unit root in
   the regression residuals; rejecting the unit-root null (small p-value)
   implies the two series are cointegrated. Only `pvalue` is kept.
5. **Acceptance:** the pair is kept only if
   `coint_pvalue <= pvalue_threshold` (default `0.05`) — note the code
   computes `metrics is None or metrics["coint_pvalue"] > pvalue_threshold`
   as the *rejection* condition, so pairs with `pvalue == pvalue_threshold`
   are kept.
6. **Additional metrics per surviving pair** (same spread computed once,
   reused for both the scan output and — if the user later calls
   `compute_spread_metrics` — recomputed independently):
   - `correlation = round(a.corr(b), 4)`
   - `hedge_ratio = round(beta, 4)`
   - `half_life_days` — see the AR(1) derivation under
     `compute_spread_metrics` below (identical `_half_life` function).
   - `current_zscore` — see the z-score formula below (identical `_zscore`
     function); pairs whose spread has zero/NaN std (degenerate) are
     dropped (`metrics is None`).
   - `spread_mean`, `spread_std` — sample mean/std of the full spread series
     over the requested history window.

Results are sorted ascending by `coint_pvalue` (strongest cointegration
first) and truncated to `limit` (default 20).

**Usage:**

```python
df = await find_cointegrated_pairs(
    provider,
    universe="sp500",
    sector="Energy",
    max_symbols=40,
    pvalue_threshold=0.05,
    min_correlation=0.7,
    limit=10,
)
```

- `provider: AbstractDataProvider`
- `universe: str = "sp500"` — universe to scan.
- `sector: str | None = None` — optional sector filter (classification
  cached 7 days).
- `max_symbols: int = 60` — cap on symbols scanned.
- `pvalue_threshold: float = 0.05` — maximum Engle-Granger p-value to keep.
- `min_correlation: float = 0.7` — correlation pre-filter gate.
- `limit: int = 20` — maximum pairs returned.

Returns a `pd.DataFrame` with columns: `symbol_a, symbol_b, correlation,
coint_pvalue, hedge_ratio, half_life_days, current_zscore, spread_mean,
spread_std`, sorted by `coint_pvalue` ascending. Empty DataFrame if fewer
than 2 symbols resolve, or no pairs survive both filters.

The agent-facing tool (`_find_cointegrated_pairs` in `tools_registry.py`)
exposes `universe`, `sector` (empty string = no filter), `max_symbols`, and
`limit` only — `pvalue_threshold` (fixed at `0.05`) and `min_correlation`
(fixed at `0.7`) are not agent-configurable. It runs under a longer timeout
(`_LONG_TOOL_TIMEOUT_SEC`) and returns "No cointegrated pairs found." when
the result is empty.

## compute_spread_metrics

**Agent-facing tool name:** `compute_spread_metrics`

**Purpose:** Computes the full tradeable-spread picture for one specific,
already-chosen pair of symbols — hedge ratio, cointegration p-value, current
z-score, mean-reversion half-life, and a concrete entry/exit trading signal.

**Why built this way:**

- Split out from `find_cointegrated_pairs` so a pair identified any other
  way (a prior scan, domain knowledge, a screener) can be evaluated
  directly without re-running a full universe scan.
- Raises `ValueError` rather than silently returning a partial/misleading
  result when there isn't enough overlapping history
  (`< _MIN_OBSERVATIONS = 120` aligned sessions) or when the resulting spread
  is degenerate (zero or NaN standard deviation, e.g. two nearly identical
  or perfectly-hedged series) — a pair-trading tool giving a confident
  z-score off 20 days of data is worse than one that refuses to answer.
- Symbols are upper-cased defensively (`symbol.upper()`) since tickers may
  arrive in any case from an agent or user.

**Math:** identical statistical machinery to `find_cointegrated_pairs`, run
once for the exact requested pair over the requested `period`:

1. **Hedge ratio (OLS):** `beta = polyfit(b, a, deg=1)[0]`, the slope of the
   least-squares fit of `a` on `b` (equivalent to simple OLS regression
   `a = alpha + beta*b`).
2. **Spread:** `spread_t = a_t - beta * b_t`.
3. **Z-score** (`_zscore`), computed over the *entire* requested history
   window (there is no separate shorter rolling window — "rolling" here
   means the full-period mean/std, recomputed fresh each call):
   ```
   zscore = (spread[-1] - spread.mean()) / spread.std()
   ```
   using pandas' default sample standard deviation (`ddof=1`); rounded to
   4dp. Returns `None` (propagates to a `ValueError`) if `std` is `0` or
   `NaN`.
4. **Half-life** (`_half_life`) — mean-reversion half-life in trading days,
   derived from an AR(1) fit of the spread:
   ```
   lagged = spread.shift(1)          # x_{t-1}
   delta  = spread.diff()            # x_t - x_{t-1}
   lambda, c = polyfit(lagged, delta, deg=1)   # delta_t = lambda * x_{t-1} + c
   ```
   This is the discrete-time Ornstein-Uhlenbeck / AR(1) mean-reversion speed
   coefficient (equivalently `x_t = (1 + lambda) * x_{t-1} + c + eps_t`). If
   `lambda >= 0` (not mean-reverting) or `abs(lambda) < 1e-12` (numerically
   indistinguishable from zero — avoids a division blow-up), the function
   returns `None`. Requires at least 20 lagged observations, else `None`.
   Otherwise:
   ```
   half_life_days = round(-ln(2) / lambda, 2)
   ```
5. **Cointegration p-value:**
   `statsmodels.tsa.stattools.coint(a, b)` — the same Engle-Granger test
   described under `find_cointegrated_pairs`, recomputed for this specific
   pair (not reused from any earlier scan).
6. **Correlation:** `round(a.corr(b), 4)` (Pearson, over the full window).

**Signal generation** (`_spread_signal`, thresholds on the current z-score):

| Condition | Signal |
|---|---|
| `z >= 2` | `"entry-zone: spread rich — short {symbol_a}, long {symbol_b}"` |
| `z <= -2` | `"entry-zone: spread cheap — long {symbol_a}, short {symbol_b}"` |
| `abs(z) <= 0.5` | `"exit-zone: spread near its mean"` |
| otherwise | `"neutral"` |

**Usage:**

```python
result = await compute_spread_metrics(provider, "XOM", "CVX", period="1y")
```

- `provider: AbstractDataProvider`
- `symbol_a: str` — first leg; spread is defined as `a - hedge_ratio * b`.
- `symbol_b: str` — second leg.
- `period: str = "1y"` — history window (agent tool documents `6mo`, `1y`,
  `2y`).

Returns a dict:

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

Raises `ValueError` when there is insufficient overlapping history
(`< 120` aligned sessions) or the spread is degenerate.

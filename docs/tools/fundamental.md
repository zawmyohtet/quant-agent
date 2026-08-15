# Fundamental Analysis Tools

`quantagent/tools/fundamental.py` implements the balance-sheet/income-statement side of the agent's
toolkit: intrinsic-value modeling (DCF), quality/distress scoring frameworks from classic equity
research (Piotroski F-Score, Altman Z-Score), and cross-sectional comparison/ranking across peers
(peer comparison table, Magic Formula ranking). Unlike `technical.py`, none of this depends on
price history — every function here takes plain Python dicts of already-fetched fundamental fields
(sourced upstream from `quantagent.tools.market_data.get_fundamentals`) or lists of numbers, and
returns either a small result dict or a `pandas.DataFrame` for tabular comparisons.

---

## compute_dcf

**Agent-facing tool name:** `compute_dcf_valuation` (module-level `@tool` in `tools_registry.py`,
not provider-bound since it needs no market data provider)

**Purpose:** Estimates a company's intrinsic (fair) value and per-share value from projected future
free cash flows, for comparing against the current market price to judge whether a stock looks
cheap or expensive on a fundamentals basis.

**Why built this way:** A standard two-stage DCF: a fixed 5-year explicit projection period grown
at a single flat `growth_rate`, followed by a Gordon Growth (perpetuity) terminal value — the
simplest and most common DCF variant, chosen over more elaborate multi-stage or fading-growth models
for tractability given the agent only has a handful of scalar assumptions to work with (no full
multi-year analyst forecast is threaded through). Growth is applied off the **last historical FCF**
in the input list (`free_cash_flows[-1]`, defaulting to `0.0` if the list is empty) rather than an
average, so a single noisy final year disproportionately drives the whole projection — a known
tradeoff of this simplification. The function raises `ValueError` up front if `discount_rate <=
terminal_growth`, since the Gordon Growth denominator `(discount_rate - terminal_growth)` would be
zero or negative otherwise, producing a nonsensical (or infinite) terminal value — this is the one
piece of input validation in the module, guarding the single spot where the math would silently
blow up or invert sign rather than just look wrong.

**Math:**
```
FCF_t = last_historical_FCF * (1 + growth_rate)^t          for t = 1..5   (5-year explicit projection)

PV_projected = Σ_{t=1..5}  FCF_t / (1 + discount_rate)^t

terminal_FCF   = FCF_5 * (1 + terminal_growth)
terminal_value = terminal_FCF / (discount_rate - terminal_growth)          (Gordon Growth Model)
PV_terminal    = terminal_value / (1 + discount_rate)^5

intrinsic_value          = PV_projected + PV_terminal
intrinsic_value_per_share = intrinsic_value / shares_outstanding
```

**Usage:**
- `compute_dcf(free_cash_flows: list[float], growth_rate: float, discount_rate: float,
  terminal_growth: float, shares_outstanding: float) -> dict` — returns
  `{"intrinsic_value", "intrinsic_value_per_share", "pv_projected", "pv_terminal",
  "projected_fcf": [5 values], "assumptions": {...}}`, all monetary values rounded to 4 decimals.
  Raises `ValueError` if `discount_rate <= terminal_growth`.
- Agent tool `compute_dcf_valuation(free_cash_flows: str, growth_rate: float, discount_rate: float,
  terminal_growth: float, shares_outstanding: float)`: `free_cash_flows` is a **comma-separated
  string** (parsed to floats), the rest are plain decimals; `shares_outstanding` is in millions.
  - Example call: `compute_dcf_valuation(free_cash_flows="100,110,125", growth_rate=0.08,
    discount_rate=0.10, terminal_growth=0.025, shares_outstanding=1500)`
- Not referenced by name in any `skills/*/SKILL.md` allowed-tools list at the time of writing.

---

## score_piotroski_f

**Agent-facing tool name:** `compute_piotroski_score` (module-level `@tool` in
`tools_registry.py`)

**Purpose:** Computes Joseph Piotroski's 9-point F-Score, a checklist for separating financially
improving ("quality") value stocks from deteriorating ones based purely on year-over-year changes in
profitability, leverage/liquidity, and operating efficiency.

**Why built this way:** Implemented as three independent evaluator helpers
(`_evaluate_profitability`, `_evaluate_leverage`, `_evaluate_efficiency`), each returning a
`(score, breakdown)` pair that the main function simply sums and merges — mirroring the textbook
F-Score's own three-bucket structure (profitability / leverage-liquidity / efficiency, each worth up
to 4/3/2 points respectively in the classic formulation, though this implementation's bucket point
totals are 4/3/2 as coded below). Every field is read via `.get(key, 0)` with numeric defaults, so
a fundamentals dict missing some fields degrades to "criterion not met" for that item instead of
raising — useful when upstream data providers don't supply every field for every symbol, at the
cost of silently under-scoring a company whose data is simply incomplete rather than genuinely
weak. Leverage ratios guard against division by zero with `max(total_assets_current, 1)` /
`max(total_assets_prior, 1)` denominators.

**Math (9 boolean criteria, 1 point each):**

*Profitability (4 points):*
1. `roa > 0` (positive return on assets)
2. `operating_cash_flow > 0`
3. `roa_current > roa_prior` (ROA improving year-over-year; falls back to comparing `roa` to itself
   — i.e. `False` — if `roa_current`/`roa_prior` aren't supplied)
4. `operating_cash_flow > net_income` (cash flow quality — earnings backed by real cash)

*Leverage / liquidity (3 points):*
5. `leverage_current < leverage_prior`, where
   `leverage = total_liabilities / max(total_assets, 1)` (declining leverage)
6. `current_ratio_current > current_ratio_prior` (improving short-term liquidity)
7. `shares_outstanding_current <= shares_outstanding_prior` (no dilution from new share issuance)

*Efficiency (2 points):*
8. `gross_margin_current > gross_margin_prior`
9. `asset_turnover_current > asset_turnover_prior`

`score = sum of all 9 booleans` (range 0–9).

**Usage:**
- `score_piotroski_f(fundamentals: dict) -> dict` — expects keys `roa`, `operating_cash_flow`,
  `net_income`, `roa_current`, `roa_prior`, `total_liabilities_current`,
  `total_liabilities_prior`, `total_assets_current`, `total_assets_prior`,
  `current_ratio_current`, `current_ratio_prior`, `shares_outstanding_current`,
  `shares_outstanding_prior`, `gross_margin_current`, `gross_margin_prior`,
  `asset_turnover_current`, `asset_turnover_prior`. Returns `{"score": int (0-9), "max_score": 9,
  "breakdown": {criterion_name: bool, ...}}`.
- Agent tool `compute_piotroski_score(fundamentals_json: str)`: takes the same fields as a JSON
  string.
  - Example call: `compute_piotroski_score(fundamentals_json='{"roa": 0.08, "operating_cash_flow":
    500, "net_income": 400, "roa_current": 0.08, "roa_prior": 0.06, ...}')`
- Not referenced by name in any `skills/*/SKILL.md` allowed-tools list at the time of writing.

---

## score_altman_z

**Agent-facing tool name:** `compute_altman_z` (module-level `@tool` in `tools_registry.py`)

**Purpose:** Computes the (public-company) Altman Z-Score, a single number estimating bankruptcy
risk from balance-sheet and market-value ratios, and buckets it into a safe/grey/distress zone —
useful as a quick sanity check before recommending a value or turnaround stock.

**Why built this way:** Implements the original 1968 Altman Z-Score formula and coefficients for
publicly traded manufacturing/general companies (using `market_cap` in the leverage term, as opposed
to the private-company variant that substitutes book value of equity) — this is the most widely
cited version and the one most fundamental data providers can populate directly from market cap plus
standard financial-statement line items. Returns an explicit early-exit result
(`{"score": None, "zone": "unknown", "reason": "total_assets <= 0"}`) if `total_assets <= 0`, since
every term in the formula divides by total assets and the ratio would be undefined or
sign-flipped for a company with zero/negative reported assets.

**Math:**
```
Z = 1.2 * (working_capital / total_assets)
  + 1.4 * (retained_earnings / total_assets)
  + 3.3 * (ebit / total_assets)
  + 0.6 * (market_cap / total_liabilities)
  + 1.0 * (sales / total_assets)
```
Zone thresholds: `Z > 2.99` → `"safe"`; `1.81 < Z <= 2.99` → `"grey"`; `Z <= 1.81` → `"distress"`.

**Usage:**
- `score_altman_z(fundamentals: dict) -> dict` — expects `working_capital`, `retained_earnings`,
  `ebit`, `total_assets`, `total_liabilities`, `sales`, `market_cap` (all default to `0`/`1` via
  `.get()` if missing — `total_assets` and `total_liabilities` default to `1` specifically to avoid
  division by zero, which can mask a genuinely missing field as a near-zero-magnitude ratio term).
  Returns `{"score": float, "zone": "safe"|"grey"|"distress"}`, or the `total_assets <= 0` early
  exit shape above.
- Agent tool `compute_altman_z(fundamentals_json: str)`: same fields as a JSON string.
  - Example call: `compute_altman_z(fundamentals_json='{"working_capital": 200, "retained_earnings":
    800, "ebit": 300, "total_assets": 2500, "total_liabilities": 1200, "sales": 3000, "market_cap":
    5000}')`
- Not referenced by name in any `skills/*/SKILL.md` allowed-tools list at the time of writing.

---

## peer_comparison

**Agent-facing tool name:** `compare_peers` (wraps `_compare_peers` in `tools_registry.py`, bound
via `_bind_provider`)

**Purpose:** Lays out a fixed set of valuation, profitability, and risk metrics side by side across
multiple symbols in one table, for comparing a stock against its sector peers at a glance.

**Why built this way:** Deliberately simple — a fixed whitelist of 11 fields
(`pe_ratio, pb_ratio, ev_ebitda, roe, roa, debt_equity, dividend_yield, eps, revenue_growth,
eps_growth, beta`) is pulled out of each symbol's fundamentals dict via `.get()` (so a missing field
becomes `None`/`NaN` in the resulting cell rather than raising), assembled into one row per symbol,
and indexed by symbol. No normalization, ranking, or scoring is applied here — that's left to the
caller (or to the LLM reading the table) to interpret; this function's only job is consistent,
tabular layout.

**Math:** None — a direct field projection/reshape, no derived formulas. Output is rounded to 4
decimals for display.

**Usage:**
- `peer_comparison(symbol_fundamentals: dict[str, dict]) -> pd.DataFrame` — `symbol_fundamentals`
  maps symbol → its fundamentals dict; returns a DataFrame indexed by `symbol` with the 11 fields
  above as columns.
- Agent tool `compare_peers(symbols: str)`: takes a comma-separated symbol string, calls
  `get_fundamentals` for each symbol to build the map, then calls `peer_comparison`; returns the
  result as JSON (`orient="index"`).
  - Example call: `compare_peers(symbols="AAPL, MSFT, GOOGL")`
- Not referenced by name in any `skills/*/SKILL.md` allowed-tools list at the time of writing.

---

## compute_magic_formula_rank

**Agent-facing tool name:** Not exposed as an agent tool — **there is no `@tool` wrapper for this
function anywhere in `tools_registry.py`**, and no other module imports it (only
`tests/unit/tools/test_fundamental.py` exercises it). It is currently unreachable by the LLM agent.

**Purpose:** Ranks a set of symbols by Joel Greenblatt's "Magic Formula" — a value + quality
screen that favors companies that are both cheap (high earnings yield) and efficient at generating
returns on invested capital (high ROC) — by combining the two rank orderings into one composite
rank per symbol.

**Why built this way:** Follows Greenblatt's original method exactly: rank each metric
independently (best value = rank 1), sum the two rank numbers per symbol, then re-rank that sum —
so a stock doesn't need to be the best on both dimensions, just strong on the combination.
`pandas.Series.rank(ascending=False, method="min")` is used so that higher ROC/earnings-yield get
rank 1, and ties share the same (minimum) rank rather than being arbitrarily broken. Both ROC and
earnings yield are computed as `None` when their denominator is non-positive (`working_capital +
fixed_assets <= 0`, or `enterprise_value <= 0`) rather than dividing by zero or a negative
denominator, which would otherwise flip the sign of the ratio and produce a misleadingly
"good"-looking negative-denominator score.

**Math:**
```
ROC             = EBIT / (Net Working Capital + Net Fixed Assets)     (None if denominator <= 0)
Earnings Yield  = EBIT / Enterprise Value                              (None if EV <= 0)

roc_rank = rank(ROC, descending, ties -> min shared rank)
ey_rank  = rank(Earnings Yield, descending, ties -> min shared rank)

magic_formula_rank = rank(roc_rank + ey_rank, ties -> min shared rank)     (lower is better)
```

**Usage:**
- `compute_magic_formula_rank(symbol_fundamentals: dict[str, dict]) -> pd.DataFrame` — each inner
  dict should have `ebit`, `working_capital`, `fixed_assets`, `enterprise_value`. Returns a
  DataFrame indexed by `symbol`, columns `magic_formula_rank` (int, ascending = best), `roc`,
  `earnings_yield` (both rounded to 4 decimals), sorted by `magic_formula_rank`.
- **Not currently callable by the LLM agent.** To make it agent-reachable it would need a
  `@tool`/`_bind_provider`-wrapped entry point in `tools_registry.py` analogous to `_compare_peers`
  (fetch fundamentals per symbol, call this function, serialize the DataFrame to JSON) plus
  registration in `build_tool_registry`.

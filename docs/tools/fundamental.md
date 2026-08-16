# Fundamental Analysis Tools

`quantagent/tools/fundamental.py`

Tools for analyzing a company's financial health using its balance sheet, income statement, and cash flow data. Unlike technical analysis (which looks at price patterns), fundamental analysis asks: "Is this a good business, and is the stock price fair?"

These tools help you answer questions like:
- **Is this stock cheap or expensive?** — Discounted Cash Flow (DCF) valuation
- **Is this company financially healthy?** — Piotroski F-Score and Altman Z-Score
- **How does this company compare to its peers?** — Peer comparison tables
- **Which stocks are the best value?** — Magic Formula ranking

All of these tools work with fundamental data (financial ratios, accounting numbers) rather than price history. They take dictionaries of financial metrics as input and return scores, rankings, or comparison tables.

---

## compute_dcf

**Agent tool:** `compute_dcf_valuation`

Estimates a company's intrinsic (fair) value based on its expected future cash flows.

### What It Does

A Discounted Cash Flow (DCF) analysis answers: "What is this company worth today, based on the cash it will generate in the future?" It's the gold standard for valuation — Warren Buffett uses it, professional analysts use it, and now you can use it too.

The basic idea:
1. Project the company's future cash flows (typically 5 years)
2. Discount those cash flows back to today's value (money tomorrow is worth less than money today)
3. Add a "terminal value" for everything beyond the projection period
4. Divide by shares outstanding to get a per-share fair value

If the fair value is higher than the current stock price, the stock is undervalued (a potential buy). If it's lower, the stock is overvalued.

### How It Works

This tool uses a **two-stage DCF model**:

**Stage 1: Explicit projection period (5 years)**
- Takes your most recent free cash flow as the starting point
- Grows it at a fixed rate for 5 years
- Discounts each year's cash flow back to today

**Stage 2: Terminal value (perpetuity)**
- Assumes cash flows continue forever, growing at a slow, sustainable rate
- Uses the Gordon Growth Model to calculate the present value of all future cash flows beyond year 5
- Discounts the terminal value back to today

**Final step:** Add the present value of the 5-year projection and the terminal value, then divide by shares outstanding to get per-share fair value.

### The Math

```
Year 1 cash flow = last_FCF × (1 + growth_rate)
Year 2 cash flow = Year 1 × (1 + growth_rate)
...
Year 5 cash flow = Year 4 × (1 + growth_rate)

Present value of each year = cash_flow / (1 + discount_rate)^year

Terminal value = Year 5 cash flow × (1 + terminal_growth) / (discount_rate - terminal_growth)
Present value of terminal = Terminal value / (1 + discount_rate)^5

Intrinsic value = Sum of present values + Present value of terminal
Per-share value = Intrinsic value / shares_outstanding
```

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `free_cash_flows` | `list[float]` | required | Historical free cash flows (the last value is used as the starting point) |
| `growth_rate` | `float` | required | Expected annual growth rate for the next 5 years (e.g. 0.08 for 8%) |
| `discount_rate` | `float` | required | Your required rate of return (e.g. 0.10 for 10%) |
| `terminal_growth` | `float` | required | Long-term sustainable growth rate (e.g. 0.025 for 2.5%) |
| `shares_outstanding` | `float` | required | Number of shares outstanding (in millions) |

### Returns

A dictionary with:
- `intrinsic_value` — total intrinsic value of the company
- `intrinsic_value_per_share` — fair value per share
- `pv_projected` — present value of the 5-year projection
- `pv_terminal` — present value of the terminal value
- `projected_fcf` — the 5 projected cash flows
- `assumptions` — the inputs used (for reference)

All monetary values are rounded to 4 decimal places.

### Usage

**Python API:**
```python
result = compute_dcf(
    free_cash_flows=[100, 110, 125],
    growth_rate=0.08,
    discount_rate=0.10,
    terminal_growth=0.025,
    shares_outstanding=1500
)
```

**Agent tool:**
```
compute_dcf_valuation(
    free_cash_flows="100,110,125",
    growth_rate=0.08,
    discount_rate=0.10,
    terminal_growth=0.025,
    shares_outstanding=1500
)
```

The agent tool takes `free_cash_flows` as a comma-separated string (which it parses into a list).

### Design Notes

**Why use the last FCF, not an average?** The tool uses the most recent free cash flow as the starting point for projections, not an average. This is simpler and more responsive to recent changes, but it means a single noisy year can disproportionately affect the valuation. If your last FCF was unusually high or low, consider using a normalized number.

**Validation:** The tool checks that `discount_rate > terminal_growth`. If not, the Gordon Growth formula breaks down (you'd be dividing by zero or a negative number). The tool raises a `ValueError` in this case rather than returning a nonsensical result.

**Not agent-callable directly.** The agent tool `compute_dcf_valuation` is registered in `tools_registry.py` but is not referenced by any skill's allowed-tools list, so the agent won't use it unless explicitly asked.

---

## score_piotroski_f

**Agent tool:** `compute_piotroski_score`

Scores a company's financial health using the Piotroski F-Score — a 9-point checklist that separates improving companies from deteriorating ones.

### What It Does

The Piotroski F-Score is a simple but powerful tool for identifying financially healthy value stocks. It asks 9 yes/no questions about a company's profitability, leverage, and efficiency. Each "yes" adds 1 point, so the score ranges from 0 (worst) to 9 (best).

A score of 7-9 indicates a financially strong company. A score of 0-2 indicates financial distress. Scores in the middle are ambiguous.

### The 9 Criteria

**Profitability (4 points):**
1. **Positive ROA** — Is return on assets positive? (The company is profitable)
2. **Positive operating cash flow** — Is cash flow from operations positive? (The company generates real cash)
3. **Improving ROA** — Is this year's ROA higher than last year's? (Profitability is improving)
4. **Cash flow > net income** — Is operating cash flow higher than net income? (Earnings are backed by real cash, not accounting tricks)

**Leverage & Liquidity (3 points):**
5. **Declining leverage** — Is this year's debt-to-assets ratio lower than last year's? (The company is paying down debt)
6. **Improving current ratio** — Is this year's current ratio higher than last year's? (Short-term liquidity is improving)
7. **No dilution** — Are shares outstanding flat or declining? (The company isn't issuing new shares)

**Efficiency (2 points):**
8. **Improving gross margin** — Is this year's gross margin higher than last year's? (The company is more efficient at producing goods)
9. **Improving asset turnover** — Is this year's asset turnover higher than last year's? (The company is generating more revenue per dollar of assets)

### How It Works

The tool takes a dictionary of fundamental data and checks each of the 9 criteria. Each criterion is a simple comparison (e.g. "Is ROA > 0?"). The tool sums up the "yes" answers to get the final score.

If a required field is missing from the input, the tool treats that criterion as "no" (0 points) rather than crashing. This means incomplete data will lower the score, which is conservative — it's better to under-score than to over-score based on missing information.

### Parameters

| Name | Type | Description |
|------|------|-------------|
| `fundamentals` | `dict` | Dictionary with financial metrics (see list below) |

**Required fields:**
- `roa`, `roa_current`, `roa_prior` — return on assets
- `operating_cash_flow`, `net_income` — cash flow and earnings
- `total_liabilities_current`, `total_liabilities_prior`, `total_assets_current`, `total_assets_prior` — for leverage ratios
- `current_ratio_current`, `current_ratio_prior` — liquidity
- `shares_outstanding_current`, `shares_outstanding_prior` — dilution check
- `gross_margin_current`, `gross_margin_prior` — profitability efficiency
- `asset_turnover_current`, `asset_turnover_prior` — operational efficiency

### Returns

A dictionary with:
- `score` — the F-Score (0-9)
- `max_score` — always 9
- `breakdown` — which criteria passed and which failed

### Usage

**Python API:**
```python
result = score_piotroski_f(fundamentals_dict)
```

**Agent tool:**
```
compute_piotroski_score(fundamentals_json='{"roa": 0.08, "operating_cash_flow": 500, ...}')
```

The agent tool takes the fundamentals as a JSON string.

### Design Notes

**Graceful degradation.** If a field is missing, the tool defaults to 0 and treats that criterion as "not met." This means incomplete data will lower the score, which is conservative. A company with missing data won't get a high score by accident.

**Division-by-zero protection.** Leverage ratios use `max(total_assets, 1)` as the denominator to avoid division by zero. This is a defensive measure — in practice, a company with zero total assets is impossible, but the protection prevents crashes on bad data.

**Not agent-callable directly.** Like DCF, this tool is registered but not referenced by any skill, so the agent won't use it unless explicitly asked.

---

## score_altman_z

**Agent tool:** `compute_altman_z`

Estimates bankruptcy risk using the Altman Z-Score — a classic formula that predicts whether a company is likely to go bankrupt in the next 2 years.

### What It Does

The Altman Z-Score combines five financial ratios into a single number that predicts bankruptcy risk. It was developed in 1968 by Edward Altman and is still widely used today.

The score falls into one of three zones:
- **Safe zone (Z > 2.99)** — low bankruptcy risk
- **Grey zone (1.81 < Z ≤ 2.99)** — moderate risk, watch carefully
- **Distress zone (Z ≤ 1.81)** — high bankruptcy risk

This is a quick sanity check before investing in a value stock or turnaround candidate. If the Z-Score is in the distress zone, you might want to think twice.

### The Formula

```
Z = 1.2 × (working_capital / total_assets)
  + 1.4 × (retained_earnings / total_assets)
  + 3.3 × (ebit / total_assets)
  + 0.6 × (market_cap / total_liabilities)
  + 1.0 × (sales / total_assets)
```

**What each term measures:**
1. **Working capital / total assets** — liquidity (can the company pay its bills?)
2. **Retained earnings / total assets** — cumulative profitability (has the company been profitable over time?)
3. **EBIT / total assets** — operating efficiency (is the core business profitable?)
4. **Market cap / total liabilities** — market confidence (does the stock market think the company is solvent?)
5. **Sales / total assets** — asset turnover (is the company generating revenue from its assets?)

### Parameters

| Name | Type | Description |
|------|------|-------------|
| `fundamentals` | `dict` | Dictionary with: `working_capital`, `retained_earnings`, `ebit`, `total_assets`, `total_liabilities`, `sales`, `market_cap` |

### Returns

A dictionary with:
- `score` — the Z-Score (float)
- `zone` — "safe", "grey", or "distress"

If `total_assets <= 0`, the tool returns `{"score": None, "zone": "unknown", "reason": "total_assets <= 0"}` rather than dividing by zero.

### Usage

**Python API:**
```python
result = score_altman_z(fundamentals_dict)
```

**Agent tool:**
```
compute_altman_z(fundamentals_json='{"working_capital": 200, "retained_earnings": 800, ...}')
```

### Design Notes

**Public company formula.** This tool uses the original 1968 formula for publicly traded manufacturing companies. There are other variants for private companies and non-manufacturing firms, but this is the most widely cited version and the one most data providers can populate.

**Market cap, not book value.** The fourth term uses market cap (market value of equity) rather than book value. This is correct for public companies — the market's assessment of equity value is more relevant than the accounting book value.

**Early exit for zero assets.** If `total_assets <= 0`, the formula would divide by zero, so the tool returns an early-exit result rather than crashing. In practice, a company with zero or negative total assets is already in serious trouble.

**Missing fields default to 0/1.** If a field is missing, it defaults to 0 (or 1 for denominators to avoid division by zero). This can mask genuinely missing data as near-zero ratios, so be aware that incomplete data will affect the score.

---

## peer_comparison

**Agent tool:** `compare_peers`

Creates a side-by-side comparison table of fundamental metrics for multiple stocks.

### What It Does

Given a list of stocks (like AAPL, MSFT, GOOG), this tool fetches their fundamental data and lays it out in a table so you can compare them at a glance. It's like putting the companies' report cards next to each other.

The comparison includes 11 key metrics:
- **Valuation:** P/E ratio, P/B ratio, EV/EBITDA
- **Profitability:** ROE, ROA
- **Leverage:** Debt-to-equity
- **Income:** EPS, dividend yield
- **Growth:** Revenue growth, EPS growth
- **Risk:** Beta

### How It Works

1. **Fetch fundamentals** — for each stock, calls `get_fundamentals()` to get its financial data
2. **Extract metrics** — pulls out the 11 key fields from each company's data
3. **Build table** — assembles everything into a pandas DataFrame with one row per stock

If a field is missing for a company, it shows up as `NaN` in the table rather than crashing. This lets you compare companies even if they don't all report the same metrics.

### Parameters

| Name | Type | Description |
|------|------|-------------|
| `symbol_fundamentals` | `dict[str, dict]` | Mapping of symbol → fundamentals dictionary |

### Returns

A pandas DataFrame with:
- **Index:** symbol (AAPL, MSFT, GOOG, etc.)
- **Columns:** `pe_ratio`, `pb_ratio`, `ev_ebitda`, `roe`, `roa`, `debt_equity`, `dividend_yield`, `eps`, `revenue_growth`, `eps_growth`, `beta`

All values are rounded to 4 decimal places.

### Usage

**Python API:**
```python
df = peer_comparison({
    "AAPL": aapl_fundamentals,
    "MSFT": msft_fundamentals,
    "GOOG": goog_fundamentals
})
```

**Agent tool:**
```
compare_peers(symbols="AAPL,MSFT,GOOG")
```

The agent tool fetches fundamentals for each symbol, then calls `peer_comparison()`. It returns the table as JSON.

### Design Notes

**No normalization or ranking.** The tool just lays out the raw numbers — it doesn't score, rank, or normalize them. That's left to you (or the LLM reading the table). This keeps the tool simple and flexible.

**Fixed set of metrics.** The tool always compares the same 11 fields. If you want to compare different metrics, you'd need to fetch the fundamentals yourself and build a custom comparison.

**Not agent-callable directly.** This tool is wrapped by `compare_peers` in the agent registry, but it's not referenced by any skill, so the agent won't use it unless explicitly asked.

---

## compute_magic_formula_rank

**Agent tool:** Not exposed to agent

Ranks stocks using Joel Greenblatt's "Magic Formula" — a simple but effective strategy that buys good companies at cheap prices.

### What It Does

The Magic Formula ranks stocks by two criteria:
1. **Earnings yield** — how cheap is the stock? (higher is better)
2. **Return on capital (ROC)** — how good is the business? (higher is better)

It ranks each stock on both criteria, adds the two ranks together, then re-ranks by the combined score. The result is a list of stocks that are both cheap and good — the "magic" combination.

### How It Works

1. **Calculate metrics** — for each stock, compute earnings yield and ROC
2. **Rank individually** — rank all stocks by earnings yield (rank 1 = highest yield), then rank by ROC (rank 1 = highest ROC)
3. **Combine ranks** — add the two ranks together for each stock
4. **Re-rank** — rank by the combined score (rank 1 = lowest combined rank = best)

A stock doesn't need to be #1 in both categories — it just needs to be strong in the combination. A stock ranked #10 in earnings yield and #5 in ROC (combined rank 15) beats a stock ranked #1 in earnings yield but #50 in ROC (combined rank 51).

### The Math

```
ROC = EBIT / (working_capital + fixed_assets)
Earnings yield = EBIT / enterprise_value

earnings_yield_rank = rank(earnings_yield, descending)
roc_rank = rank(ROC, descending)

magic_formula_rank = rank(earnings_yield_rank + roc_rank, ascending)
```

If the denominator is zero or negative (e.g. negative working capital), the metric is set to `None` and the stock is excluded from ranking.

### Parameters

| Name | Type | Description |
|------|------|-------------|
| `symbol_fundamentals` | `dict[str, dict]` | Mapping of symbol → fundamentals dictionary (must include `ebit`, `working_capital`, `fixed_assets`, `enterprise_value`) |

### Returns

A pandas DataFrame with:
- **Index:** symbol
- **Columns:** `magic_formula_rank` (1 = best), `roc`, `earnings_yield`

Sorted by `magic_formula_rank` (ascending, so rank 1 is first).

### Usage

**Python API:**
```python
df = compute_magic_formula_rank({
    "AAPL": aapl_fundamentals,
    "MSFT": msft_fundamentals,
    ...
})
```

**Agent tool:** Not exposed. This function is not wrapped in the agent tool registry, so the agent cannot call it. It's only accessible from Python code.

### Design Notes

**Ties share ranks.** If two stocks have the same earnings yield, they get the same rank (using pandas' `method="min"` ranking). This is fair — neither stock is penalized for the tie.

**Excludes bad data.** If ROC or earnings yield can't be computed (denominator ≤ 0), the stock is excluded from ranking rather than getting a misleadingly "good" score from a negative denominator.

**Not agent-callable.** This function has no wrapper in `tools_registry.py`, so the agent cannot use it. To make it agent-accessible, you'd need to add a wrapper similar to `compare_peers`.

---

## Summary

These fundamental analysis tools help you evaluate companies from a financial perspective:

- **DCF valuation** — "What is this company worth based on its future cash flows?"
- **Piotroski F-Score** — "Is this company financially healthy and improving?"
- **Altman Z-Score** — "Is this company at risk of bankruptcy?"
- **Peer comparison** — "How does this company stack up against its competitors?"
- **Magic Formula** — "Which stocks are both cheap and good?"

Use these tools together for a complete fundamental picture. For example, you might:
1. Screen for cheap stocks (low P/E)
2. Check their Piotroski scores (are they financially healthy?)
3. Check their Altman Z-Scores (are they at risk of bankruptcy?)
4. Run a DCF valuation (what are they really worth?)
5. Compare them to peers (which is the best in its sector?)

This kind of systematic, multi-factor analysis is what professional investors do. Now you can do it too.

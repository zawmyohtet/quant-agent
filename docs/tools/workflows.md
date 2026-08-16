# Workflow Tools

`quantagent/tools/workflows.py`

Tools for chaining multiple analysis steps into reusable workflows. A workflow is just a sequence of tool calls — run this, then that, then this again — with the output of each step available as input to the next.

Workflows are orchestration only, no analytical math of their own. They let you automate common multi-step analysis routines.

---

## What Is a Workflow?

A workflow is an ordered list of steps. Each step:
1. Calls a registered tool function (like `get_market_summary` or `screen_stocks`)
2. Stores the result under a named key (like "market" or "candidates")
3. Can reference previous results using `$key` or `$key.field` placeholders

Workflows can be:
- **Built-in** — pre-defined Python functions (like `daily_market_check`)
- **Custom** — user-defined YAML files stored at `~/.quantagent/workflows/<name>.yaml`

Both types execute through the same engine, so custom workflows have the same capabilities as built-in ones.

---

## Built-in Workflows

QuantAgent comes with five pre-defined workflows:

| Workflow | What it does | Target required? |
|----------|--------------|------------------|
| `daily_market_check` | Market snapshot, sector performance, rotation, conviction score | No |
| `weekly_sector_review` | Sector ranking, relative strength, rotation detection | No |
| `stock_research` | Quote, fundamentals, and news for one stock | Yes (symbol) |
| `screening_pipeline` | Market regime check, then fundamental screen | No |
| `portfolio_rebalance_review` | Portfolio risk metrics, then optimization suggestions | Yes (symbols) |

---

## list_workflows

**Agent tool:** `list_workflows_tool`

Lists all available workflows — the five built-ins plus any custom YAML workflows you've created.

### What It Does

Returns a list of workflow names and descriptions you can run. Built-in workflows are listed first, followed by custom workflows in alphabetical order.

### Parameters

None.

### Returns

A list of dictionaries with:
- `name` — workflow name
- `type` — "builtin" or "custom"
- `description` — what the workflow does

### Usage

**Python API:**
```python
workflows = list_workflows()
# [
#   {"name": "daily_market_check", "type": "builtin", "description": "..."},
#   {"name": "my_morning_routine", "type": "custom", "description": "..."}
# ]
```

**Agent tool:**
```
list_workflows_tool()
```

---

## run_workflow

**Agent tool:** `run_workflow_tool`

Executes a workflow — runs all the steps in sequence and returns the results.

### What It Does

Takes a workflow name (and optional target), resolves it to a workflow definition, then executes each step in order. Each step's output is stored and made available to subsequent steps via `$key` references.

### How It Works

1. **Resolve workflow** — looks up the workflow by name (built-in or custom YAML)
2. **Validate target** — if the workflow requires a target (like a symbol), checks that one was provided
3. **Execute steps** — runs each step in sequence:
   - Look up the tool function in the registry
   - Resolve any `$key` references in the parameters
   - Call the function with the resolved parameters
   - Store the result under the step's `output_key`
4. **Return results** — returns a `WorkflowResult` with all step outputs and a summary

**Sequential execution:** Steps run one after another, not in parallel. Each step waits for the previous one to complete. This ensures dependencies are satisfied (step 2 can use step 1's output).

**Fail-fast:** If any step raises an exception, the entire workflow aborts. There's no per-step error handling — a broken step should fail loudly rather than silently produce a partial result.

### Parameters

| Name | Type | Description |
|------|------|-------------|
| `name` | `str` | Workflow name (built-in or custom) |
| `target` | `str \| None` | Optional target (symbol or comma-separated symbols) |

### Returns

A `WorkflowResult` with:
- `name` — workflow name
- `completed_at` — timestamp
- `step_results` — dictionary mapping output_key → result
- `summary` — human-readable summary of what each step produced

### Usage

**Python API:**
```python
result = await run_workflow(provider, daily_market_check())
result.step_results["conviction"]  # conviction score
result.summary  # "- market (get_market_summary): dict (...)\n- ..."
```

**Agent tool:**
```
run_workflow_tool(name="daily_market_check")
run_workflow_tool(name="stock_research", target="AAPL")
run_workflow_tool(name="portfolio_rebalance_review", target="AAPL,MSFT,GOOGL")
```

---

## daily_market_check

**Agent tool:** `run_workflow_tool(name="daily_market_check")`

The recurring "how does the market look today" routine.

### What It Does

Runs a comprehensive market check:
1. Overall market snapshot (indices, timing, breadth, sentiment)
2. Sector performance ranking
3. Sector rotation detection
4. Conviction score with exposure guidance

### The Steps

1. `get_market_summary` → output_key: "market"
2. `get_sector_performance_ranked` → output_key: "sectors"
3. `detect_sector_rotation` → output_key: "rotation"
4. `synthesize_conviction` → output_key: "conviction"

**Why this order?** Steps are ordered from broad to narrow context, ending in the synthesis step. The conviction score fuses all the earlier signals, so it runs last to incorporate everything.

### Parameters

None (no target required).

### Usage

**Python API:**
```python
workflow = daily_market_check()
result = await run_workflow(provider, workflow)
```

**Agent tool:**
```
run_workflow_tool(name="daily_market_check")
```

**Estimated duration:** 1-2 minutes.

---

## weekly_sector_review

**Agent tool:** `run_workflow_tool(name="weekly_sector_review")`

A sector-focused analysis for weekly review.

### What It Does

Drills into sector-level analysis:
1. Rank sectors by performance
2. Compute relative strength vs. benchmark
3. Detect rotation patterns

### The Steps

1. `get_sector_performance_ranked` → output_key: "ranking"
2. `compute_sector_relative_strength` → output_key: "rs"
3. `detect_sector_rotation` → output_key: "rotation"

### Parameters

None (no target required).

### Usage

**Python API:**
```python
workflow = weekly_sector_review()
result = await run_workflow(provider, workflow)
```

**Agent tool:**
```
run_workflow_tool(name="weekly_sector_review")
```

**Estimated duration:** 1-2 minutes.

---

## stock_research

**Agent tool:** `run_workflow_tool(name="stock_research", target="AAPL")`

A quick deep dive on a single stock.

### What It Does

Gathers comprehensive information on one stock:
1. Current quote (price, volume, market cap)
2. Fundamental data (P/E, ROE, debt, etc.)
3. Recent news headlines

### The Steps

1. `get_quote(symbol=symbol)` → output_key: "quote"
2. `get_fundamentals(symbol=symbol)` → output_key: "fundamentals"
3. `get_news(symbol=symbol)` → output_key: "news"

**Why this order?** Cheapest/most-time-sensitive first (quote), then slower-changing structural data (fundamentals), then qualitative context (news). A natural "what is it doing, what is it, why" reading order.

### Parameters

| Name | Type | Description |
|------|------|-------------|
| `target` | `str` | **Required.** Stock symbol (e.g. "AAPL") |

### Usage

**Python API:**
```python
workflow = stock_research("AAPL")
result = await run_workflow(provider, workflow)
```

**Agent tool:**
```
run_workflow_tool(name="stock_research", target="AAPL")
```

**Estimated duration:** Under 1 minute.

---

## screening_pipeline

**Agent tool:** `run_workflow_tool(name="screening_pipeline")`

Establishes market context before running a stock screen.

### What It Does

Checks the market regime first, then runs a fundamental screen. This lets you interpret screen results in light of whether the market favors offense or defense.

### The Steps

1. `detect_market_regime` → output_key: "regime"
2. `screen_stocks(criteria=criteria or {})` → output_key: "candidates"

**Why this order?** Regime is checked first because screening criteria (momentum vs. value tilts) are typically interpreted differently in a risk-on vs. risk-off regime. Putting regime first gives context without forcing the screen to depend on it.

### Parameters

None (no target required). Screen criteria are not parameterizable through the agent tool — it always runs with default (empty) criteria.

### Usage

**Python API:**
```python
workflow = screening_pipeline({"pe_lt": 15, "roe_gt": 0.15})
result = await run_workflow(provider, workflow)
```

**Agent tool:**
```
run_workflow_tool(name="screening_pipeline")
```

**Estimated duration:** 2-4 minutes.

---

## portfolio_rebalance_review

**Agent tool:** `run_workflow_tool(name="portfolio_rebalance_review", target="AAPL,MSFT,GOOGL")`

A portfolio health check with optimization suggestions.

### What It Does

Analyzes a portfolio's current risk profile, then suggests an optimized allocation:
1. Compute risk metrics (beta, VaR, tracking error) for equal-weight allocation
2. Run max-Sharpe optimization to suggest better weights

### The Steps

1. `compute_portfolio_metrics(weights=equal_weights)` → output_key: "risk"
2. `optimize_portfolio(symbols=symbols, method="max_sharpe")` → output_key: "optimization"

**Why equal weight first?** The tool only receives a symbol list, not actual position sizes, so it assumes equal weighting as a neutral baseline. Then it runs optimization so you can compare "if I were equal-weight, here's my risk" against "here's what an optimizer would recommend."

### Parameters

| Name | Type | Description |
|------|------|-------------|
| `target` | `str` | **Required.** Comma-separated symbols (e.g. "AAPL,MSFT,GOOGL") |

### Usage

**Python API:**
```python
workflow = portfolio_rebalance_review(["AAPL", "MSFT", "GOOGL"])
result = await run_workflow(provider, workflow)
```

**Agent tool:**
```
run_workflow_tool(name="portfolio_rebalance_review", target="AAPL,MSFT,GOOGL")
```

**Estimated duration:** 1-2 minutes.

---

## Custom Workflows

You can define your own workflows in YAML files stored at `~/.quantagent/workflows/<name>.yaml`.

### YAML Format

```yaml
name: my_morning_routine
description: "My personal morning market review"
estimated_duration: "2-3 minutes"
steps:
  - tool: get_market_summary
    parameters: {}
    output_key: market
  - tool: screen_oversold_reversal
    parameters: {rsi_threshold: 35}
    output_key: candidates
  - tool: get_news
    parameters: {symbol: $candidates.symbol, days: 7}
    output_key: news
```

### Step Fields

Each step has three fields:
- `tool` — the tool function name (must be in `STEP_REGISTRY`)
- `parameters` — dictionary of parameters (can reference previous outputs with `$key`)
- `output_key` — name to store the result under (must be unique within the workflow)

### Parameter References

You can reference previous step outputs using `$key` syntax:
- `$key` — the entire output of the step with output_key "key"
- `$key.field` — a specific field from that output (if it's a dict)

Example:
```yaml
steps:
  - tool: screen_stocks
    parameters: {universe: "sp500"}
    output_key: candidates
  - tool: get_news
    parameters: {symbol: $candidates.symbol}  # reference previous output
    output_key: news
```

### Loading Custom Workflows

Custom workflows are loaded automatically when you run them by name. You don't need to register them — just create the YAML file and run it.

**Python API:**
```python
workflow = load_custom_workflow("my_morning_routine")
result = await run_workflow(provider, workflow)
```

**Agent tool:**
```
run_workflow_tool(name="my_morning_routine")
```

---

## STEP_REGISTRY

**Agent tool:** Not exposed (internal)

A dictionary mapping tool names to the actual functions that implement them. This is the "whitelist" of tools that can be used in workflows.

### What It Does

Maps string names (like "get_market_summary") to async functions. When a workflow step specifies `tool: get_market_summary`, the engine looks up the function in this registry and calls it.

### Why a Registry?

A closed registry (rather than dynamic import/eval of arbitrary function names) means custom YAML workflows can only invoke a vetted set of functions. This makes it safe to let users supply their own workflow YAML without risking arbitrary code execution.

### Available Tools

The registry includes tools from:
- `market_data` — get_ohlcv, get_quote, get_fundamentals, etc.
- `market_overview` — get_market_summary, get_top_movers, etc.
- `market_breadth` — detect_market_regime, compute_percent_above_ma, etc.
- `sector_analysis` — get_sector_performance_ranked, detect_sector_rotation, etc.
- `screener` — screen_stocks, screen_by_technicals, etc.
- `portfolio` — optimize_portfolio, compute_portfolio_metrics, etc.
- `conviction` — synthesize_conviction
- `pair_trading` — find_cointegrated_pairs, compute_spread_metrics
- `event_analysis` — analyze_earnings_impact, get_earnings_calendar_range

All functions have the signature `async fn(provider, **kwargs) -> Any`.

---

## Summary

These workflow tools let you chain multiple analysis steps into reusable routines:

- **list_workflows** — see what workflows are available
- **run_workflow** — execute a workflow
- **Built-in workflows** — daily_market_check, weekly_sector_review, stock_research, screening_pipeline, portfolio_rebalance_review
- **Custom workflows** — define your own in YAML

Use workflows to:
- Automate common multi-step analysis routines
- Ensure consistent analysis across multiple stocks or portfolios
- Create reusable templates for your investment process
- Chain tools together without writing Python code

Remember: workflows are orchestration only — they don't do any analysis themselves, they just call other tools in sequence. The real work happens in the individual tool functions. Workflows just make it easy to run the same sequence of tools over and over.

Custom workflows are especially powerful — they let you define your own analysis routines in YAML without touching Python. Want a workflow that checks the market regime, screens for oversold stocks, and then pulls news on the candidates? Just write a YAML file and run it.

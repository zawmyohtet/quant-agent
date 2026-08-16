# Report Generation Tools

`quantagent/tools/reports/`

Tools for generating comprehensive analysis reports that combine multiple data sources and analyses into a single, readable document. Reports are available in both Markdown and HTML formats.

---

## What Are Reports?

Reports are structured documents that pull together multiple analyses into a coherent narrative. Instead of running individual tools and manually combining the results, a report generator:

1. Calls multiple analysis tools in sequence
2. Packages their outputs into organized sections
3. Renders everything into a formatted document (Markdown or HTML)
4. Saves it to disk for review or sharing

Reports use **graceful degradation** — if one section fails (e.g. data unavailable), the rest of the report still renders. You get a partial report with an error note in the failed section, rather than no report at all.

---

## Available Reports

| Report | What it covers | Agent tool |
|--------|----------------|------------|
| Market Daily | Market overview, regime, timing, breadth, sentiment, sectors, movers | `generate_report_tool(report_type="market")` |
| Sector Deep-Dive | Sector performance, relative strength, rotation, technicals, industries | `generate_report_tool(report_type="sector", target="Technology")` |
| Stock Deep-Dive | Quote, technicals, fundamentals, news for one stock | `generate_report_tool(report_type="stock", target="AAPL")` |
| Portfolio Review | Allocation, risk metrics, sector exposure, optimization, Monte Carlo | `generate_report_tool(report_type="portfolio", target="AAPL,MSFT,GOOGL")` |
| Screening Summary | Screen parameters, results, and disclaimer | `generate_report_tool(report_type="screening", target="fundamental")` |

---

## generate_report_tool

**Agent tool:** `generate_report_tool`

The main entry point for generating reports. Dispatches to the appropriate generator based on `report_type`.

### What It Does

Takes a report type and optional target, generates the report, saves it to disk, and returns a preview to the agent.

### Parameters

| Name | Type | Description |
|------|------|-------------|
| `report_type` | `str` | Report type: "market", "sector", "stock", "portfolio", or "screening" |
| `target` | `str \| None` | Target (sector name, stock symbol, comma-separated symbols, or screen type) |
| `criteria` | `str \| None` | JSON string of screen criteria (screening reports only) |
| `universe` | `str` | Universe for screening (default: "sp500") |
| `format` | `str` | Output format: "markdown" or "html" (default: "markdown") |

### Returns

A preview of the generated report (first few sections as Markdown).

### Usage

**Agent tool:**
```
generate_report_tool(report_type="market")
generate_report_tool(report_type="stock", target="AAPL")
generate_report_tool(report_type="sector", target="Technology")
generate_report_tool(report_type="portfolio", target="AAPL,MSFT,GOOGL")
generate_report_tool(report_type="screening", target="fundamental", criteria='{"pe_lt": 15}')
```

---

## Report Models

### ReportConfig

Configuration options for report generation.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `title` | `str` | `""` | Custom title (overrides auto-generated title) |
| `format` | `str` | `"markdown"` | Output format ("markdown" or "html") |
| `date_range` | `str` | `"1y"` | Historical data range (for stock reports) |
| `benchmark` | `str` | `"SPY"` | Benchmark for comparisons |

### ReportSection

One section of a report.

| Field | Type | Description |
|-------|------|-------------|
| `title` | `str` | Section title |
| `content` | `str` | Markdown content |
| `tables` | `list[pd.DataFrame]` | Data tables to render |

### Report

The complete report document.

| Field | Type | Description |
|-------|------|-------------|
| `title` | `str` | Report title |
| `generated_at` | `datetime` | Timestamp |
| `sections` | `list[ReportSection]` | Report sections |
| `metadata` | `dict` | Additional metadata (type, symbol, etc.) |

---

## safe_section

**Internal helper** (not exposed to agent)

Wraps a section builder to catch exceptions and degrade gracefully.

### What It Does

If a section's data fetch or analysis fails, `safe_section` catches the exception and returns a placeholder section with an error message instead of crashing the entire report.

### How It Works

```python
async def safe_section(title: str, builder: Coroutine) -> ReportSection:
    try:
        return await builder
    except Exception as exc:
        return ReportSection(title=title, content=f"_Data unavailable ({exc})._")
```

### Why This Matters

Reports often depend on external data providers, which can be flaky. Without graceful degradation, a single failed API call would prevent the entire report from generating. With `safe_section`, you get a partial report with honest error notes rather than no report at all.

---

## Market Daily Report

**Generator:** `generate_market_daily`

A comprehensive daily market briefing.

### What It Covers

1. **Market Overview** — major indices (SPY, QQQ, DIA, IWM) with trends
2. **Market Regime & Exposure** — regime score, confidence, recommended exposure
3. **Timing Signals** — distribution days, follow-through day status
4. **Breadth** — % of stocks above key moving averages
5. **Sentiment** — fear & greed score and components
6. **Sector Performance** — ranked sector returns
7. **Sector Rotation** — leading/lagging sectors, cycle phase
8. **Top Movers** — biggest gainers and losers (if cache is warm)

### How It Works

1. Calls `get_market_summary` once to get most of the data
2. Calls sector analysis tools for sector-specific data
3. Checks if breadth cache is warm before attempting top movers
4. Assembles all sections into a report
5. Renders to Markdown or HTML
6. Saves to `~/.quantagent/reports/market-<timestamp>.md`

### Usage

**Python API:**
```python
report = await generate_market_daily(provider)
```

**Agent tool:**
```
generate_report_tool(report_type="market")
```

**Slash command (deterministic, no LLM):**
```
/market report
```

---

## Sector Report

**Generator:** `generate_sector_report`

A deep dive into a specific market sector.

### What It Covers

1. **Performance** — sector rank and returns across timeframes
2. **Relative Strength** — RS ratio vs. benchmark, trend
3. **Rotation Context** — is the sector leading, lagging, improving, or deteriorating?
4. **Technical Summary** — sector ETF technicals (trend, momentum, volatility)
5. **Industry Breakdown** — industries within the sector, ranked by performance

### How It Works

1. Fuzzy-matches the sector name to one of the 11 GICS sectors
2. Calls sector analysis tools for performance, RS, and rotation data
3. Fetches sector ETF price data for technical analysis
4. Calls industry performance tool for breakdown
5. Assembles and renders the report

### Parameters

| Name | Type | Description |
|------|------|-------------|
| `sector` | `str` | Sector name (e.g. "Technology", "Healthcare") |
| `config` | `ReportConfig \| None` | Optional configuration |

### Usage

**Python API:**
```python
report = await generate_sector_report(provider, sector="Technology")
```

**Agent tool:**
```
generate_report_tool(report_type="sector", target="Technology")
```

**Slash command:**
```
/sector Technology report
```

---

## Stock Report

**Generator:** `generate_stock_report`

A comprehensive analysis of a single stock.

### What It Covers

1. **Company Overview** — quote, sector/industry classification
2. **Technical Analysis** — trend, momentum, volatility, support/resistance, patterns
3. **Fundamental Analysis** — valuation ratios, profitability, growth metrics
4. **Recent News** — latest headlines with sentiment

### How It Works

1. Fetches quote and classification data
2. Downloads price history and runs technical analysis
3. Fetches fundamental data
4. Fetches recent news
5. Assembles and renders the report

**Note:** DCF valuation and F-Score are not auto-included because they require specific inputs (FCF projections, balance sheet history) that can't be assumed. Call those tools explicitly if needed.

### Parameters

| Name | Type | Description |
|------|------|-------------|
| `symbol` | `str` | Stock ticker |
| `config` | `ReportConfig \| None` | Optional configuration (date_range controls lookback) |

### Usage

**Python API:**
```python
report = await generate_stock_report(provider, symbol="AAPL")
```

**Agent tool:**
```
generate_report_tool(report_type="stock", target="AAPL")
```

**Slash command:**
```
/stock AAPL report
```

---

## Portfolio Report

**Generator:** `generate_portfolio_report`

A comprehensive portfolio analysis with optimization suggestions.

### What It Covers

1. **Allocation** — current weights (equal-weight if not specified)
2. **Risk Metrics** — beta, VaR, CVaR, tracking error, information ratio
3. **Sector Exposure** — how much is in each sector
4. **Optimization Suggestion** — max-Sharpe optimized weights
5. **Monte Carlo Simulation** — distribution of possible outcomes

### How It Works

1. Normalizes weights (equal-weight if not provided)
2. Computes portfolio risk metrics vs. benchmark
3. Classifies holdings by sector
4. Runs optimization to suggest better allocation
5. Runs Monte Carlo simulation for probabilistic outlook
6. Assembles and renders the report

### Parameters

| Name | Type | Description |
|------|------|-------------|
| `symbols` | `list[str]` | List of stock tickers |
| `weights` | `dict[str, float] \| None` | Optional weights (equal-weight if omitted) |
| `config` | `ReportConfig \| None` | Optional configuration |

### Usage

**Python API:**
```python
report = await generate_portfolio_report(
    provider,
    symbols=["AAPL", "MSFT", "GOOGL"],
    weights={"AAPL": 0.4, "MSFT": 0.35, "GOOGL": 0.25}
)
```

**Agent tool:**
```
generate_report_tool(report_type="portfolio", target="AAPL,MSFT,GOOGL")
```

**Note:** There is no deterministic slash command for portfolio reports — they always go through the agent.

---

## Screening Report

**Generator:** `generate_screening_report`

A summary of a stock screen with parameters and results.

### What It Covers

1. **Parameters** — screen type, universe, criteria (self-documenting)
2. **Results** — table of matching stocks
3. **Notes** — disclaimer that screen output is candidates, not advice

### How It Works

1. Dispatches to the appropriate screen function based on `screen_type`
2. Runs the screen with the provided criteria
3. Packages results into a report with parameters and disclaimer

### Available Screen Types

| Screen Type | Description |
|-------------|-------------|
| `fundamental` | Filter by valuation, profitability, growth metrics |
| `technical` | Filter by technical indicators (RSI, MACD, etc.) |
| `vcp` | Volatility Contraction Pattern (Minervini) |
| `breakout` | Stocks near 52-week highs on volume |
| `oversold` | Oversold stocks showing reversal signs |

### Parameters

| Name | Type | Description |
|------|------|-------------|
| `screen_type` | `str` | Screen type (see table above) |
| `criteria` | `dict \| None` | Screen criteria |
| `universe` | `str` | Universe to screen (default: "sp500") |
| `config` | `ReportConfig \| None` | Optional configuration |

### Usage

**Python API:**
```python
report = await generate_screening_report(
    provider,
    screen_type="fundamental",
    criteria={"pe_lt": 15, "roe_gt": 0.15},
    universe="sp500"
)
```

**Agent tool:**
```
generate_report_tool(
    report_type="screening",
    target="fundamental",
    criteria='{"pe_lt": 15, "roe_gt": 0.15}',
    universe="sp500"
)
```

**Slash command (deterministic, default fundamental screen):**
```
/screen report
```

---

## Report Rendering

Reports can be rendered to Markdown or HTML.

### Markdown

Simple, readable format. Tables are rendered as GitHub-style pipe tables.

```markdown
## Market Overview

**SPY:** 512.30 (+0.42%) — Trend: up
**QQQ:** 445.10 (+0.68%) — Trend: up
...
```

### HTML

Self-contained HTML page with inline CSS and automatic dark mode support. Tables are rendered as styled HTML tables.

### Rendering Process

1. **Flatten report** — convert Report object to template context
2. **Render tables** — convert DataFrames to Markdown or HTML tables
3. **Apply template** — use Jinja2 templates to render the full document
4. **Write to disk** — save to `~/.quantagent/reports/<slug>-<timestamp>.<ext>`

---

## Summary

These report generation tools create comprehensive analysis documents:

- **Market Daily** — broad market overview with regime, timing, breadth, sentiment, sectors
- **Sector Report** — deep dive into one sector with performance, RS, rotation, industries
- **Stock Report** — comprehensive analysis of one stock with technicals, fundamentals, news
- **Portfolio Report** — portfolio analysis with risk metrics, optimization, Monte Carlo
- **Screening Report** — screen results with parameters and disclaimer

Use reports to:
- Get a daily market briefing
- Deep dive into a specific sector or stock
- Review your portfolio's risk and optimization opportunities
- Document screen results for later review

Reports are saved to `~/.quantagent/reports/` and can be opened in any Markdown or HTML viewer. They're a great way to capture your analysis and share it with others.

Remember: reports use graceful degradation — if one section fails, the rest still renders. You get a partial report with honest error notes rather than no report at all. This makes reports robust even when data providers are flaky.

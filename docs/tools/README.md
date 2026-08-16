# QuantAgent Tools Reference

Welcome to the tools documentation. This directory contains plain-English guides to every analysis tool in QuantAgent — from technical indicators to portfolio optimization to market breadth analysis.

---

## What Are Tools?

Tools are the building blocks of QuantAgent's analysis capabilities. Each tool does one specific thing:

- Fetch market data (prices, fundamentals, news)
- Calculate technical indicators (RSI, MACD, moving averages)
- Run screens (find stocks matching your criteria)
- Analyze market breadth (how many stocks are participating in a move)
- Optimize portfolios (find the best allocation)
- Backtest strategies (see how a strategy would have performed)
- Generate reports (combine multiple analyses into a document)

Tools are composed together by the agent to answer your questions. When you ask "What's the market regime?", the agent calls the appropriate tools, interprets the results, and gives you a plain-English answer.

---

## How These Docs Are Organized

Each markdown file covers one module (a group of related tools). The docs follow a consistent structure:

1. **What it does** — plain-English explanation of the tool's purpose
2. **How it works** — the logic and algorithms, explained simply
3. **Parameters** — what inputs the tool takes
4. **Returns** — what the tool gives back
5. **Usage** — how to call it (Python API and agent tool)
6. **Design notes** — why it's built this way

You don't need to understand the math to use the tools — the agent handles that. But if you're curious about how things work under the hood, the math is there too.

---

## Tool Index

### Market Data & Infrastructure

| File | What it covers |
|------|----------------|
| [market_data.md](market_data.md) | Fetching prices, quotes, fundamentals, news, earnings |
| [providers.md](providers.md) | Data provider abstraction (yfinance, Alpha Vantage, Polygon) |
| [cache.md](cache.md) | Caching system to avoid redundant API calls |
| [universe.md](universe.md) | Stock universes (S&P 500, Nasdaq 100, custom watchlists) |

### Technical Analysis

| File | What it covers |
|------|----------------|
| [technical.md](technical.md) | Indicators (RSI, MACD, moving averages), patterns, support/resistance |
| [backtesting.md](backtesting.md) | Testing strategies against historical data |

### Fundamental Analysis

| File | What it covers |
|------|----------------|
| [fundamental.md](fundamental.md) | DCF valuation, Piotroski F-Score, Altman Z-Score, peer comparison |
| [event_analysis.md](event_analysis.md) | Earnings analysis and calendars |

### Market Analysis

| File | What it covers |
|------|----------------|
| [market_breadth.md](market_breadth.md) | Distribution days, follow-through days, advance/decline, market regime |
| [market_overview.md](market_overview.md) | Market summary, top movers, most active stocks, heatmaps |
| [sector_analysis.md](sector_analysis.md) | Sector performance, rotation, relative strength |
| [conviction.md](conviction.md) | Composite market conviction score (0-100) |
| [breadth_store.md](breadth_store.md) | Cache for universe-level breadth calculations |

### Stock Screening

| File | What it covers |
|------|----------------|
| [screener.md](screener.md) | Fundamental screens, technical screens, VCP pattern, breakouts, oversold reversal |

### Portfolio Management

| File | What it covers |
|------|----------------|
| [portfolio.md](portfolio.md) | Portfolio optimization, risk metrics, Monte Carlo simulation |
| [pair_trading.md](pair_trading.md) | Statistical arbitrage, cointegration, spread trading |

### Trading Discipline

| File | What it covers |
|------|----------------|
| [trade_journal.md](trade_journal.md) | Trade logging, lifecycle management, MAE/MFE, performance stats |
| [risk_gate.md](risk_gate.md) | Circuit breaker, pre-trade discipline checks |

### Orchestration & Reporting

| File | What it covers |
|------|----------------|
| [workflows.md](workflows.md) | Chaining tools into multi-step workflows |
| [reports.md](reports.md) | Generating comprehensive analysis reports |

---

## Agent Tools vs. Internal Functions

Not every function in the codebase is exposed to the agent. Some are internal helpers used by other tools.

**Agent tools** are wrapped with `@tool` and registered in `tools_registry.py`. The agent can call these directly to answer your questions.

**Internal functions** are not exposed to the agent. They're used internally by other tools or workflows. You can still call them from Python, but the agent won't use them directly.

Each doc file notes which functions are agent-callable and which are internal.

---

## Data Flow

Here's how data flows through the system:

```
You ask a question
    ↓
Agent interprets and plans
    ↓
Agent calls tools (market_data, technical, fundamental, etc.)
    ↓
Tools fetch data from providers (yfinance, Alpha Vantage, Polygon)
    ↓
Tools analyze data (calculate indicators, run screens, etc.)
    ↓
Agent interprets results
    ↓
Agent gives you a plain-English answer
```

The tools layer is where the heavy lifting happens. The agent is the orchestrator — it decides which tools to call and how to interpret the results.

---

## Provider Abstraction

All tools that need market data take a `provider: AbstractDataProvider` as their first argument. This lets you switch between data sources (yfinance, Alpha Vantage, Polygon) without changing any analysis code.

See [providers.md](providers.md) for details on the three supported providers and how to configure them.

---

## Where to Start

If you're new to QuantAgent, here's a suggested reading order:

1. **[market_data.md](market_data.md)** — understand how data flows into the system
2. **[technical.md](technical.md)** — learn about the most common analysis tools
3. **[screener.md](screener.md)** — see how to find stocks matching your criteria
4. **[market_breadth.md](market_breadth.md)** — understand market-level analysis
5. **[conviction.md](conviction.md)** — see how everything comes together into a single score

From there, explore the other modules based on what you want to do. Each module is self-contained — you don't need to read them in order.

---

## Questions?

These docs are written to be readable by both developers and non-technical users. If something is unclear, please open an issue or submit a PR to improve the docs.

The goal is to make QuantAgent's capabilities transparent and understandable — no black boxes, no magic. You should always be able to understand what the tools are doing and why.

# QuantAgent

[![CI](https://github.com/zawmyohtet/quant-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/zawmyohtet/quant-agent/actions/workflows/ci.yml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Type Check](https://img.shields.io/badge/mypy-typed-blue)](https://github.com/python/mypy)
[![SonarQube Cloud](https://sonarcloud.io/images/project_badges/sonarcloud-light.svg)](https://sonarcloud.io/summary/new_code?id=zawmyohtet_quant-agent)

> Your AI quant analyst in the terminal.

QuantAgent is a terminal UI application that lets you chat with an AI agent to analyze stocks, backtest strategies, optimize portfolios, and screen markets — all backed by live data and rigorous quantitative methods.

## Features

- **Conversational Analysis** — Ask natural language questions about any stock or portfolio. The agent plans multi-step analyses and ends with a clear stance, conviction score, and actionable levels.
- **Live Market Data** — OHLCV, quotes, fundamentals, and news via yfinance, Alpha Vantage, or Polygon.
- **Technical Analysis** — SMA, EMA, RSI, MACD, Bollinger Bands, ATR, ADX, OBV, Stochastic, VWAP, Supertrend, plus candlestick pattern detection and support/resistance levels.
- **Fundamental Analysis** — DCF valuation, Piotroski F-Score, Altman Z-Score, peer comparison, Magic Formula ranking.
- **Backtesting** — Built-in strategies (SMA/EMA crossover, RSI mean reversion, MACD momentum, Bollinger breakout) with Sharpe, drawdown, win rate, and walk-forward validation.
- **Portfolio Tools** — Optimize weights (max Sharpe, min vol, risk parity, equal weight), compute risk metrics (beta, VaR, CVaR), and run Monte Carlo simulations.
- **Stock Screener** — Filter S&P 500, Nasdaq-100, Dow 30, or custom universes by fundamentals and technicals, plus pattern screens (Minervini VCP, 52-week-high breakouts, oversold reversals).
- **Market Analysis** — Market regime detection (cross-asset ratios + breadth) with recommended equity-exposure bands, sector rotation and relative strength, distribution-day / Follow-Through-Day timing signals, universe-wide breadth (A/D line, new highs/lows, breadth thrust), sentiment, and a conviction synthesizer that fuses it all into one score (`/market`, `/sector`, `/market heatmap`).
- **Pair Trading & Earnings Events** — Cointegration scanning with hedge ratio, z-score, and half-life spread metrics; historical earnings-reaction analysis (gap, day-1 move, post-earnings drift) and universe earnings calendars.
- **Reports & Workflows** — Generate Markdown/HTML market, sector, stock, portfolio, and screening reports (`/report`); run multi-step analysis workflows, including custom YAML workflows (`/workflow`).
- **Trade Journal & Risk Discipline** — Forward-only trade journal with MAE/MFE capture, drawdown circuit breaker, and a pre-trade discipline gate, all surfaced together in `/journal`.
- **Human-in-the-Loop** — Approve sensitive actions like backtests and portfolio optimization before they run.

## ⚠️ Important Disclaimer

- **For Informational Purposes Only:** This project does **NOT** constitute financial advice, investment advice, or a recommendation to buy or sell any security.
- **Advisory Only:** QuantAgent is strictly an advisory tool and does not execute automated trades. It provides data-driven insights and trade plans for human review.
- **Risk Warning:** All investments carry risk, including possible loss of principal. Past performance is not indicative of future results.

## Quick Start

### Requirements

- Python >= 3.12
- [uv](https://github.com/astral-sh/uv) (recommended)

### Install

#### Standalone Binary (macOS / Linux)

Download the latest release for your platform — no Python or `uv` required.

```bash
# macOS
curl -L -o quantagent https://github.com/zawmyohtet/quant-agent/releases/latest/download/quantagent-macos
chmod +x quantagent
sudo mv quantagent /usr/local/bin/

# Linux
curl -L -o quantagent https://github.com/zawmyohtet/quant-agent/releases/latest/download/quantagent-linux
chmod +x quantagent
sudo mv quantagent /usr/local/bin/
```

#### From Source

```bash
# Clone the repository
git clone git@github.com:zawmyohtet/quant-agent.git
cd quant-agent

# Create virtual environment and install dependencies
uv sync

# (Optional) Set your API keys in ~/.quantagent/.env
echo "OPENAI_API_KEY=sk-..." >> ~/.quantagent/.env
echo "ANTHROPIC_API_KEY=sk-ant-..." >> ~/.quantagent/.env
echo "ZAI_API_KEY=..." >> ~/.quantagent/.env
```

### Run

```bash
# Launch the TUI
uv run quantagent

# Or with options
uv run quantagent --model openai:gpt-4o --provider yfinance
```

`zai:` models use Z.AI's OpenAI-compatible API. By default QuantAgent targets
`https://api.z.ai/api/paas/v4/`. Override that with `ZAI_API_BASE` if needed.

### First Commands

```
/stock AAPL                 # full AI analysis of a stock
/stock AAPL quick           # fast deterministic snapshot (no AI turn)
/stock AAPL MSFT GOOGL      # peer comparison
/market                     # market regime, breadth, timing, exposure
/screen pe_lt:15 roe_gt:0.20
/backtest MSFT sma_crossover
/help
```

Type `/` to browse every command with autocomplete, or see the full
[Commands](#commands) reference below.

## Commands

Type `/` in the input bar to open the command menu with fuzzy autocomplete — press `Tab`/`Enter` to complete, `Esc` to dismiss. Anything that isn't a slash command is sent to the AI agent as a normal question. Older command names are kept as **aliases** (e.g. `/analyze` → `/stock`), so existing muscle memory keeps working.

### Analysis modes

The four analysis commands — `/stock`, `/market`, `/sector`, `/screen` — share one pattern: a trailing **mode** word controls *how* the work runs.

| Mode | Speed | How it works |
|---|---|---|
| _(default)_ | slower | Full AI analysis — the agent plans multiple steps and narrates a conclusion. |
| `quick` | fast | Runs a fixed data pipeline directly (no AI turn) and prints the results. |
| `report` | fast | Generates a formatted Markdown report saved to `~/.quantagent/reports/`. |

Type a space after the command (and its argument) to see the available modes in the dropdown — no need to memorize them.

### Analysis

- **`/stock <SYMBOL…> [quick|report]`** — Analyze one or more stocks. Aliases: `/analyze`, `/compare`.
  - `/stock AAPL` — full AI analysis: quote, technicals, fundamentals, valuation, news.
  - `/stock AAPL quick` — fast snapshot: quote, fundamentals, recent news.
  - `/stock AAPL report` — save a full stock report.
  - `/stock AAPL MSFT GOOGL` — peer comparison.
- **`/market [quick|report|heatmap]`** — Market overview: regime, breadth, timing signals, sector performance, recommended exposure. Alias: `/heatmap`.
  - `/market` — AI market briefing.
  - `/market quick` — deterministic daily market check.
  - `/market report` — save a market report.
  - `/market heatmap [metric]` — sector heatmap (`metric`: `performance`, `volume`, `volatility`, `rsi`).
- **`/sector [name] [quick|report]`** — Sector analysis and rotation.
  - `/sector` — rank all sectors by performance and relative strength.
  - `/sector technology` — deep dive on one sector.
  - `/sector quick` — deterministic weekly sector review.
  - `/sector technology report` — save a sector report (a sector name is required for `report`).
- **`/screen <criteria> [quick|report]`** — Screen stocks against your criteria.
  - `/screen pe_lt:15 roe_gt:0.20` — AI screen honoring your free-text criteria.
  - `/screen quick` — deterministic screening pipeline (standard criteria).
  - `/screen report` — save a screening report. _Free-text criteria are honored only in the default (AI) mode; `quick`/`report` run the standard screen._
- **`/backtest <SYMBOL> <strategy>`** — Backtest a strategy. Strategies: `sma_crossover`, `ema_crossover`, `rsi_mean_reversion`, `macd_momentum`, `bollinger_breakout`, `buy_and_hold`. Example: `/backtest MSFT sma_crossover`.

### Workflows & reports

- **`/workflow [name] [target]`** — Run a predefined multi-step workflow; run bare (`/workflow`) to pick from a menu. Built-ins: `daily_market_check`, `weekly_sector_review`, `stock_research <symbol>`, `screening_pipeline`, `portfolio_rebalance_review <symbols>`. Custom YAML workflows live in `~/.quantagent/workflows/`. Alias: `/workflows`.
- **`/report [type] [target]`** — Generate a Markdown/HTML report; run bare to pick from a menu. Types: `market`, `sector <name>`, `stock <symbol>`, `portfolio <symbols>`, `screening`. Saved to `~/.quantagent/reports/`.
- **`/journal [add <SYMBOL> <thesis>]`** — View the trade journal (open trades, history, stats) alongside the risk circuit-breaker / discipline status. `/journal add TSLA "breakout retest"` logs a new idea. Alias: `/riskgate`.

### Data

| Command | Description |
|---|---|
| `/universe [name]` | Switch the active screening universe; run bare to pick from a menu. Built-ins: `sp500`, `nasdaq100`, `dow30`, `sector_etfs`. Alias: `/universes`. |
| `/warm [universe]` | Pre-warm the breadth cache (`sp500` / `nasdaq100` / `sector_etfs`) for faster breadth stats. |

### Session & configuration

| Command | Description |
|---|---|
| `/new` | Start a fresh conversation thread. |
| `/threads` | Open the thread switcher. |
| `/clear` | Clear the visible transcript. |
| `/export [path]` | Export the current thread to Markdown. |
| `/stop` | Cancel the running agent turn. |
| `/retry` | Re-send the last message. |
| `/help [command]` | List commands, or show detail for one. |
| `/exit` | Quit (alias: `/quit`). |
| `/model <provider:model>` | Set the LLM (e.g. `openai:gpt-4o`). |
| `/provider <name>` | Switch data provider (`yfinance`, `alpha_vantage`, `polygon`). |
| `/theme [name]` | List or switch the UI theme. |
| `/apikey <provider> <key>` | Save an API key to `~/.quantagent/.env`. |
| `/memory` | Print your `QUANTAGENT.md` memory file. |

## Configuration

All user data lives in `~/.quantagent/`:

| File | Purpose |
|---|---|
| `config.toml` | Model, provider, disabled skills, approval list |
| `.env` | API keys (chmod 600) |
| `QUANTAGENT.md` | Personal memory — portfolio, preferences, watchlist (injected every turn) |
| `skills/` | Custom skill overrides and new skills |
| `sessions.db` | Thread history |

## Architecture

QuantAgent is split into four loosely coupled layers:

```
TUI (Textual)  ←──AgentEvent queue──→  Adapter (AgentRunner)
                                              │
                                        Agent (LangGraph + deepagents)
                                              │
                                        Tools (pandas-ta, vectorbt)
                                              │
                                        Providers (yfinance, Alpha Vantage, Polygon)
```

The TUI never imports agent or tools directly. All coupling flows through `adapter/events.py` and `AgentRunner`.

## Development

```bash
# Run the app
uv run quantagent

# Run tests
uv run pytest

# Lint and type-check
uv run ruff check . --fix
uv run mypy .
```

See [`AGENTS.md`](AGENTS.md) for detailed contributor guidelines.

## Data Providers

| Provider | API Key | Real-Time | Best For |
|---|---|---|---|
| **yfinance** | No | 15 min delay | Free, no setup, broad coverage |
| **Alpha Vantage** | Yes | 15 min delay | Structured fundamentals |
| **Polygon** | Yes | Yes | Real-time quotes, options, crypto |

Switch providers anytime with `/provider <name>`.

## Skills

Skills are on-demand domain knowledge modules (backtesting, risk management, indicator playbooks). The agent loads only the skills relevant to your question, keeping context lean. You can override built-in skills or add your own in `~/.quantagent/skills/`.

## Acknowledgements

The **terminal UX, slash-command model, and overall CLI shape** are intentionally inspired by **[deepagents-cli](https://github.com/langchain-ai/deepagents/tree/main/libs/cli)** (the reference Deep Agents terminal experience) and **[OpenCode](https://opencode.ai)**. QuantAgent is a **separate, quant-specialized** codebase that depends on the same SDK—not a fork of the CLI library.

This project also took some inspiration from **[claude-trading-skills](https://github.com/tradermonty/claude-trading-skills)** (trading-focused skill workflows for Claude).

## License

MIT

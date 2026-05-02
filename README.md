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
- **Stock Screener** — Filter S&P 500 and Nasdaq-100 by fundamentals and technicals.
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
```

### Run

```bash
# Launch the TUI
uv run quantagent

# Or with options
uv run quantagent --model openai:gpt-4o --provider yfinance
```

### First Commands

```
/analyze AAPL
/backtest MSFT sma_crossover
/screen pe_lt:15 roe_gt:0.20
/compare AAPL MSFT GOOGL
/help
```

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

## License

MIT

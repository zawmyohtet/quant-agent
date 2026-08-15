# QuantAgent — Product Specification

> What QuantAgent does today, in plain English. Describes the current app — not a roadmap. Keep this file in sync with the code whenever features, commands, or providers change.

## 1. What it is

QuantAgent is a terminal-based AI quant analyst. You chat with it inside a fast, keyboard-driven terminal window, and it fetches live market data, runs technical and fundamental analysis, backtests strategies, optimizes portfolios, screens stocks, and — beyond single-stock analysis — reads the whole market: sector rotation, market breadth, and a bull/bear regime with a concrete "how much should I be invested" answer. It can also generate saved reports, run repeatable workflows, and keep a trade journal with basic risk discipline checks.

**Value proposition:** institutional-grade quant analysis, in a terminal, with an AI that plans multi-step work and explains its reasoning — not just a chart viewer.

## 2. Who it's for

- Retail traders and quant hobbyists who want fast, data-driven answers.
- Developers and analysts who prefer terminal workflows over web dashboards.
- People who want repeatable, backtested strategies rather than one-off opinions.

## 3. Core features

### 3.1 Conversational analysis
- Ask about any stock, sector, or the market as a whole in plain English.
- The agent plans multi-step work itself (fetch data → compute indicators → backtest → summarize).
- A full analysis ends with a **stance** (Bullish / Bearish / Neutral), a **conviction score (1–10)**, and **actionable levels** (entry, target, stop).

### 3.2 Market data
- Real-time and historical price history (OHLCV), quotes, fundamentals, and news.
- Three providers: **yfinance** (free), **Alpha Vantage** (free tier, API key), **Polygon** (real-time on paid plans, API key). Switch anytime with `/provider`.

### 3.3 Technical analysis
- Indicators: SMA, EMA, RSI, MACD, Bollinger Bands, ATR, ADX, OBV, Stochastic, VWAP, Supertrend.
- Candlestick patterns: Doji, Engulfing, Hammer, Shooting Star, Morning/Evening Star, Three White Soldiers, Three Black Crows.
- Support and resistance detection, and an automatic technical summary (trend, momentum, volatility, volume).

### 3.4 Fundamental analysis
- DCF valuation with custom assumptions.
- Piotroski F-Score and Altman Z-Score.
- Peer comparison tables.

### 3.5 Backtesting
- Built-in strategies: SMA crossover, EMA crossover, RSI mean reversion, MACD momentum, Bollinger breakout, buy-and-hold.
- Metrics: CAGR, Sharpe, Sortino, Calmar, max drawdown, win rate, profit factor.
- Walk-forward analysis (to catch overfitting) and parameter optimization via grid search.

### 3.6 Portfolio management
- Optimization methods: max Sharpe, min volatility, risk parity, equal weight.
- Risk metrics: beta, VaR (95/99), CVaR, tracking error, information ratio.
- Monte Carlo simulation.

### 3.7 Stock screening
- Screen a named universe (S&P 500, Nasdaq-100, or your own custom list) by:
  - **Fundamentals** — P/E, P/B, ROE, ROA, debt/equity, market cap, dividend yield, and more.
  - **Technicals** — RSI level, MACD crossover, price vs. moving average, volume expansion, ADX trend strength.
  - **Combined** filters (fundamentals + technicals together).
  - Specialized pattern screens: **VCP** (Minervini volatility-contraction pattern), **breakout candidates** (near 52-week highs with volume), **oversold reversal** (RSI-based bounce candidates).
- Manage your own custom universes (create/list/delete) alongside the built-in ones.

### 3.8 Market-wide analysis
Beyond single stocks, QuantAgent reads the whole market:
- **Market regime detection** — a bull/bear/neutral read using cross-asset ratios, trend, volatility, and breadth, with an explicit **recommended equity-exposure band** (not just a label).
- **Sector rotation** — ranks sectors and industries by performance and relative strength, flags leading/lagging/improving/deteriorating sectors and where we are in the cycle.
- **Market breadth & timing** — advance/decline line, new highs/lows, breadth thrust, percent of stocks above key moving averages, IBD-style distribution-day counts, and O'Neil Follow-Through Day detection.
- **Market sentiment** — a composite score from breadth, momentum, and volatility.
- **Top movers, most active, and a sector/industry heatmap.**
- **Conviction synthesizer** — fuses regime, breadth, timing, sector rotation, and sentiment into one 0–100 score, rewarding agreement across independent signals, with exposure guidance and key risks called out.

### 3.9 Reports
Generate and save a report as Markdown or HTML for: market overview, a specific sector, a specific stock (deep-dive), a portfolio, or a screening run.

### 3.10 Workflows
Run a saved, multi-step sequence in one command:
- **Built-in:** daily market check, weekly sector review, stock research, screening pipeline, portfolio rebalance review.
- **Custom:** define your own in `~/.quantagent/workflows/<name>.yaml`.

### 3.11 Trade journal & risk discipline
- Log a trade idea with a thesis, entry plan, target, and stop.
- Status moves forward only (`idea → entry_ready → active → partially_closed → closed / invalidated`) — no retroactively rewriting history.
- On close, QuantAgent computes your realized P&L plus MAE/MFE (maximum adverse/favorable excursion during the trade) for honest postmortems.
- Journal stats: win rate, average win/loss, profit factor, expectancy, max consecutive losses.
- **Drawdown circuit breaker** — flags when daily/weekly/monthly losses (or a losing streak) should pause new entries.
- **Discipline gate** — blocks a trade idea from moving to "entry ready" if it's missing a thesis or stop, the circuit breaker is tripped, or the market regime says reduce-only.
- These only give recommendations — QuantAgent never places trades or touches a broker.

### 3.12 Pair trading & earnings analysis
- Find cointegrated stock pairs for statistical arbitrage; compute spread hedge ratio, z-score, and half-life for a chosen pair.
- Analyze how a stock has historically reacted to earnings, and pull an earnings calendar across a date range or universe.

### 3.13 Human-in-the-loop approval
By default, three sensitive tools require your explicit approval before running: `run_backtest_tool`, `optimize_portfolio_tool`, `delete_universe_tool`. Configurable via `config.toml` (`approval_required`).

## 4. User interface

### 4.1 Layout
- **Message view** — scrollable chat history: user messages, streamed agent responses, collapsible tool-call cards (with live progress on long-running tools), system notifications, and error banners.
- **Status bar** — current activity (idle / thinking / running a specific tool, with elapsed seconds), model, provider, thread ID, token count.
- **Chat input** — multiline input with `/`-command autocomplete (arrow keys navigate suggestions and mode keywords).
- **Footer** — Textual's built-in key-hint footer.
- **Help screen** (`F1`) — every command grouped by category, plus the current keybindings.
- **Thread selector** (`Ctrl+T`) — switch or delete past conversations.
- **Picker modal** — pops up when `/workflow`, `/report`, or `/universe` is run with no argument, so you can pick from a list instead of remembering the exact name.
- **Approval dialog** — modal shown when a sensitive tool needs your sign-off.

### 4.2 Keyboard shortcuts
| Key | Action |
|---|---|
| `Enter` | Send message |
| `F1` | Open help screen |
| `Ctrl+C` | Quit |
| `Ctrl+T` | Open thread selector |
| `Ctrl+N` | New thread |
| `Ctrl+L` | Clear visible messages |
| `Escape` | Cancel the running agent turn |
| `Ctrl+P` | Command palette (Textual built-in, includes the theme picker) |
| `↑ / ↓` | Navigate the `/`-command autocomplete dropdown |

## 5. Slash commands

Several analysis commands support optional **mode** keywords (`quick`, `report`, and — for `/market` only — `heatmap`). `quick` and `report` skip the AI and run a fast, deterministic pipeline instead; leaving the mode off sends a free-form request to the agent, which can reason, combine tools, and answer follow-up questions.

### Session
| Command | Purpose |
|---|---|
| `/new` | Start a fresh conversation thread |
| `/threads` | Open the thread selector |
| `/clear` | Clear visible messages |
| `/export [path]` | Export the current thread as Markdown |
| `/stop` | Cancel the currently running agent turn |
| `/retry` | Re-submit your last message |
| `/help [command]` | Show available commands, or help for one |
| `/exit` (alias `/quit`) | Quit QuantAgent |

### Config
| Command | Purpose |
|---|---|
| `/model <provider:model>` | Set the LLM model (e.g. `anthropic:claude-sonnet-4-6`, `opencode:<model>`) |
| `/provider <name>` | Set the market-data provider (`yfinance` / `alpha_vantage` / `polygon`) |
| `/theme [name]` | List themes, or switch the UI theme |
| `/apikey <provider> <key>` | Save an API key to `~/.quantagent/.env` |

### Analysis
| Command | Purpose |
|---|---|
| `/stock <SYMBOL...> [quick\|report]` (aliases `/analyze`, `/compare`) | Analyze one stock, or compare several. `quick` runs the stock-research pipeline directly; `report` generates and saves a stock report. |
| `/market [quick\|report\|heatmap]` (alias `/heatmap`) | Market overview: regime, breadth, timing signals, exposure. `quick` runs the daily market check; `report` saves a market report; `heatmap [metric]` asks for a sector heatmap. |
| `/sector [name] [quick\|report]` | Sector analysis — all sectors ranked, or one sector by name. `quick` runs the weekly sector review; `report` saves a sector report (requires a name). |
| `/screen <criteria> [quick\|report]` | Screen stocks matching free-text criteria (e.g. `pe_lt:15 roe_gt:0.20`). `quick` runs the screening pipeline; `report` saves a screening report. |
| `/backtest <SYMBOL> <strategy>` | Run a backtest for a symbol using a named strategy |

### Workflows & Reports
| Command | Purpose |
|---|---|
| `/workflow [name] [target]` (alias `/workflows`) | Pick and run a saved workflow — no name opens a picker menu |
| `/report [type] [target]` | Pick and generate a report — no type opens a picker menu (`market`, `sector`, `stock`, `portfolio`, `screening`) |
| `/journal [add <SYMBOL> <thesis>]` (alias `/riskgate`) | View the trade journal and circuit-breaker status, or log a new trade idea |

### Data
| Command | Purpose |
|---|---|
| `/universe [name]` (alias `/universes`) | Pick the active screening universe — no name opens a picker menu |
| `/warm [universe]` | Warm the breadth cache for a universe (`sp500` / `nasdaq100` / `sector_etfs`) so market-breadth commands run fast afterward |

## 6. Skills system

Skills give the agent **on-demand domain knowledge** instead of bloating the system prompt with everything up front.

**How it works**
1. At startup, the agent only reads each skill's short `description`.
2. When you ask something, the agent matches relevant skills by that description.
3. Only matched skills' full instructions (and any reference files) get loaded.

**Precedence (last wins for a same-named skill):** built-in skills → your overrides in `~/.quantagent/skills/` → extra directories you configure.

**Built-in skills:**
| Skill | Covers |
|---|---|
| `advanced-screening` | Value/momentum/oversold/breakout/VCP screens, custom universes |
| `backtesting` | Backtest methodology, Sharpe/drawdown interpretation, walk-forward validation |
| `data-sources` | Which data/fields each provider actually supports |
| `earnings-analysis` | Earnings-reaction behavior, calendars, post-earnings drift |
| `exposure-discipline` | Position sizing, trading discipline, journal review, pre-entry risk gating |
| `indicator-playbook` | Indicator interpretation, choosing indicators for the current regime |
| `market-breadth` | Advance/decline, new highs/lows, breadth thrust, distribution/follow-through days |
| `market-regime` | Bull/bear regime detection, equity exposure, market health |
| `pair-trading` | Cointegration, hedge ratios, spread trading |
| `report-generation` | Generating and exporting reports |
| `risk-framework` | Position sizing, stops, VaR, drawdown limits |
| `sector-rotation` | Sector leadership, relative strength, economic-cycle positioning |
| `strategy-patterns` | Trend-following vs. mean-reversion system design per regime |

## 7. Persistence

- **Thread history** — every conversation is saved to SQLite and can be resumed after restarting the app (`/threads`, `Ctrl+T`).
- **Config** — `~/.quantagent/config.toml` stores your model, provider, theme, approval list, and any skill overrides/disabled skills.
- A separate `studio_sessions.db` exists only for local LangGraph Studio debugging — it's not part of normal app usage.

## 8. Data providers

| Provider | Key required | Real-time | Best for |
|---|---|---|---|
| **yfinance** | No | 15-min delay | Free, broad coverage, no setup |
| **Alpha Vantage** | Yes | 15-min delay | Fundamentals, structured data |
| **Polygon** | Yes | Yes | Real-time quotes, options, crypto |

Rate limits and per-provider field coverage are documented in the `data-sources` skill.

## 9. Security & configuration

- API keys live in `~/.quantagent/.env` (chmod 600) — never in `config.toml`.
- `.env` and any key/secret files are gitignored.
- Three tools require your approval by default before running: `run_backtest_tool`, `optimize_portfolio_tool`, `delete_universe_tool`.
- Error logs (with full context for debugging) go to `~/.quantagent/logs/errors.log`.
- The drawdown circuit breaker and pre-trade discipline gate (§3.11) only ever produce recommendations — QuantAgent never executes trades or connects to a broker.

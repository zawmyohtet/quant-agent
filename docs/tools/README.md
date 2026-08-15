# QuantAgent Tools Reference

This directory documents every quant function in `quantagent/tools/` — one markdown file per
module, mirroring the module reference in [`docs/architecture.md` §4.4](../architecture.md).
Each function's doc follows the same four-part structure:

- **Purpose** — the trading/investing problem it solves, in plain language.
- **Why built this way** — the design rationale visible in the code (library choice, algorithm
  variant, defaults, degradation behavior).
- **Math** — the actual formula/thresholds/constants implemented, pulled from the source (not
  textbook memory) — including any place the code's real behavior differs from what its name or
  docstring implies.
- **Usage** — parameters, return shape, a realistic example call, and the agent-facing `@tool`
  name it's wrapped as in `quantagent/agent/tools_registry.py` (or a note that it isn't exposed to
  the LLM at all).

`tools/` code never touches the TUI or agent graph directly — see the dependency rules in
`docs/architecture.md` §3. Functions that need market data take `provider: AbstractDataProvider`
as their first argument rather than instantiating one; see [`providers.md`](providers.md).

## Index

| File | Module | Covers |
|---|---|---|
| [technical.md](technical.md) | `technical.py` | Indicators (SMA/EMA/RSI/MACD/BBands/ATR/ADX/OBV/Stochastic/VWAP/Supertrend), candlestick pattern detection, support/resistance, rule-based signal generation, technical summaries |
| [fundamental.md](fundamental.md) | `fundamental.py` | DCF valuation, Piotroski F-Score, Altman Z-Score, peer comparison, Magic Formula rank (not agent-callable) |
| [backtesting.md](backtesting.md) | `backtesting.py` | vectorbt-based single backtest, walk-forward validation, parameter grid search, result formatting |
| [portfolio.md](portfolio.md) | `portfolio.py` | Portfolio optimization (max Sharpe / min vol / risk parity / equal weight), risk metrics (beta, VaR, CVaR, tracking error, information ratio), Monte Carlo simulation |
| [screener.md](screener.md) | `screener.py` | Fundamental/technical/combined screens, Minervini VCP pattern, breakout candidates, oversold reversal |
| [universe.md](universe.md) | `universe.py` | Built-in and custom symbol universes used as the search space for screens and breadth math |
| [market_breadth.md](market_breadth.md) | `market_breadth.py` | Distribution days, follow-through days, % above MA, advance/decline, new highs/lows, breadth thrust, composite market regime + exposure band, sentiment |
| [breadth_store.md](breadth_store.md) | `breadth_store.py` | `BreadthStore` — incremental SQLite OHLCV cache that makes universe-wide breadth math fast |
| [sector_analysis.md](sector_analysis.md) | `sector_analysis.py` | Sector/industry performance ranking, symbol classification, relative strength, sector rotation detection |
| [market_overview.md](market_overview.md) | `market_overview.py` | One-shot market summary rollup, top movers, most active, heatmap generation |
| [conviction.md](conviction.md) | `conviction.py` | Fuses regime, breadth, timing, rotation, and sentiment into one 0–100 conviction score with stance + exposure guidance |
| [pair_trading.md](pair_trading.md) | `pair_trading.py` | Engle-Granger cointegration scan, hedge ratio / z-score / half-life / signal for a pair |
| [event_analysis.md](event_analysis.md) | `event_analysis.py` | Historical earnings-reaction stats, earnings calendar range lookup |
| [workflows.md](workflows.md) | `workflows.py` | Multi-step orchestration: built-in and custom (YAML) workflows chaining other tools |
| [market_data.md](market_data.md) | `market_data.py` | Thin async pass-throughs to the active `AbstractDataProvider` |
| [cache.md](cache.md) | `cache.py` | `DataCache` — general-purpose async cache (JSON + DataFrame) backing a few other tools |
| [trade_journal.md](trade_journal.md) | `trade_journal.py` | Trade idea lifecycle, MAE/MFE, win rate/profit factor/expectancy stats |
| [risk_gate.md](risk_gate.md) | `risk_gate.py` | Circuit breaker (drawdown/loss-streak limits) and pre-entry discipline gate — recommendations only, never touches a broker |
| [providers.md](providers.md) | `providers/` | `AbstractDataProvider` contract + the three concrete providers (yfinance, Alpha Vantage, Polygon) and selection logic |
| [reports.md](reports.md) | `reports/` | Report generators that compose other tools into market/sector/stock/portfolio/screening reports, with graceful per-section degradation |

## Notable cross-cutting findings

A few things surfaced while writing these docs:

- **Not every function is agent-callable.** `compute_magic_formula_rank` (fundamental.py),
  `get_sector_etf_heatmap`/`compute_sector_correlation` (sector_analysis.py), `run_walkforward`/
  `optimize_parameters` (backtesting.py), and most of `breadth_store.py`/`cache.py` have no `@tool`
  wrapper in `tools_registry.py` — they exist in the codebase but the LLM cannot invoke them today.
  Each file notes this explicitly where it applies.

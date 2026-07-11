# QuantAgent — Market Analysis Expansion Plan

> Roadmap and specification for transforming QuantAgent from single-stock analysis into a comprehensive market analysis platform.

## 1. Overview

QuantAgent currently excels at single-stock analysis: technical indicators, fundamental scoring, backtesting, and portfolio optimization. This spec outlines the plan to expand capabilities into **market-wide analysis** — sector rotation, industry analysis, market breadth, market regime detection, advanced screening, report generation, and workflow automation.

**Goal:** Transform QuantAgent into a robust market analysis tool that can generate reports by industry, sector, track trending stocks, and provide market-level intelligence comparable to institutional research platforms — with every market-level score translated into **actionable exposure guidance**, not just description.

**Reference:** This plan draws inspiration from [claude-trading-skills](https://github.com/tradermonty/claude-trading-skills), a Claude Code skills-based trading workflow toolkit. Concepts adopted:

- Market regime detection via **cross-asset ratios** (RSP/SPY, IWM/SPY, XLY/XLP, SPY/TLT, HYG/LQD)
- Breadth analysis with composite scoring mapped to **explicit equity-exposure bands**
- **Follow-Through Day / distribution-day** market-timing signals (O'Neil), computable from index data alone
- Sector rotation and cycle positioning
- Workflow composition (ordered steps with output passing)
- A **conviction synthesizer** that fuses sub-analyses into one score with signal-convergence weighting
- Trade journaling with a forward-only lifecycle, MAE/MFE capture, and postmortem analysis
- A **risk-gating stack**: drawdown circuit breaker + pre-trade discipline gate

**Data strategy (design constraint):** Free **yfinance-first**. Every Phase 1 capability must have a *fast path* that works on the free tier from a handful of index/ETF tickers. Universe-wide computation (500+ symbols) is a *deep path* that is cache-mandatory and incrementally maintained. Paid providers (Polygon grouped bars, future FMP) are accelerators, never requirements.

## 2. Current Capabilities (Baseline)

| Module | Current State |
|---|---|
| `tools/technical.py` | 11 indicators (SMA, EMA, RSI, MACD, BBands, ATR, ADX, OBV, Stoch, VWAP, Supertrend), 8 candlestick patterns, 5 signal strategies, support/resistance, correlation matrix |
| `tools/fundamental.py` | DCF, Piotroski F-Score, Altman Z-Score, peer comparison, Magic Formula ranking |
| `tools/backtesting.py` | vectorbt backtest engine, walk-forward analysis, parameter optimization (Sharpe, max drawdown live here) |
| `tools/portfolio.py` | 4 optimization methods; `compute_portfolio_metrics` covers beta, VaR 95/99, CVaR, tracking error, information ratio; Monte Carlo simulation |
| `tools/screener.py` | S&P 500 / Nasdaq-100 screening (Wikipedia-scraped constituents) with fundamental filters; capped at 100 symbols, sequential fetching |
| `tools/market_data.py` | Thin wrappers: OHLCV, quotes, fundamentals, earnings calendar, news, symbol search, sector performance, economic indicators |
| `tools/providers/` | 3 providers: yfinance (free), Alpha Vantage (API key), Polygon (API key). `AbstractDataProvider` already includes `get_sector_performance()` and `get_economic_indicators()` |

Known defects in the baseline (fixed in Phase 0):

- Screener `rsi_lt`/`rsi_gt` criteria exist in `_CRITERIA_DISPATCH` but `_build_screening_row` emits no `rsi` column — the filters silently no-op.
- `buy_and_hold` is advertised in the backtest tool docstring (`agent/tools_registry.py`) but `technical.py::_STRATEGY_DISPATCH` has no handler — it produces all-zero signals.
- `russell2000` is advertised as a screening universe but has no entry in `screener.py::_UNIVERSE_URLS` — it silently returns empty.
- `tools/screener.py` has no unit tests.

## 3. Gap Analysis

| Capability | Status | Priority |
|---|---|---|
| Baseline defect fixes (RSI filter, buy_and_hold, russell2000, screener tests) | Broken/missing | HIGH (Phase 0) |
| Caching layer + batch data fetching | Missing (portfolio/screener fetch sequentially) | HIGH (Phase 0) |
| Sector & industry analysis | Partial (`get_sector_performance` exists but limited) | HIGH |
| Market breadth indicators (A/D line, new highs/lows, % above MA) | Missing | HIGH |
| Market-timing signals (Follow-Through Day, distribution days) | Missing | HIGH |
| Market regime detection (cross-asset + breadth composite) | Missing | HIGH |
| Exposure guidance (regime/breadth score → equity-exposure band) | Missing | HIGH |
| Advanced multi-factor screening | Missing | HIGH |
| Custom universe support | Missing | MEDIUM |
| Report generation (market, sector, stock) | Missing | MEDIUM |
| Workflow composition & automation | Missing | MEDIUM |
| Conviction synthesizer (multi-signal fusion) | Missing | MEDIUM |
| Trade journaling & memory | Missing | LOW |
| Risk-gating stack (circuit breaker, discipline gate) | Missing | LOW |
| Pair trading / statistical arbitrage | Missing | LOW |
| Additional data providers (FMP, Alpaca) | Missing | LOW |

## 4. Phase 0 — Prerequisites & Fixes

**Priority:** HIGH | **Effort:** 3-4 days | **Dependencies:** None

Everything in Phase 1+ depends on batch fetching and caching; several planned extensions build on modules that are currently subtly broken or untested. Fix the foundation first.

### 4.1 Baseline Bug Fixes

| Fix | Location | Detail |
|---|---|---|
| RSI screening filters no-op | `tools/screener.py` | Either compute RSI in `_build_screening_row` (requires an OHLCV fetch per symbol — gate behind a flag) or remove `rsi_lt`/`rsi_gt` from `_CRITERIA_DISPATCH` and the tool docstring until Phase 2's `screen_by_technicals` lands |
| `buy_and_hold` strategy missing | `tools/technical.py`, `agent/tools_registry.py` | Add a `_signal_buy_and_hold` handler to `_STRATEGY_DISPATCH` (buy on first bar, hold) — or remove it from the docstring and `/backtest` help |
| `russell2000` silently empty | `tools/screener.py`, `agent/tools_registry.py` | Remove from advertised universes. There is no free, reliable Russell 2000 constituent source; reintroduce later gated on a paid provider (see §6.2, §10.1) |
| Screener untested | `tests/unit/tools/test_screener.py` | Add baseline unit tests (mock provider, canned Wikipedia tables) before Phase 2 extends the module |

### 4.2 Caching Layer

**New file:** `quantagent/tools/cache.py`

```python
class DataCache:
    """Local cache for market data to reduce API calls.
    Storage: ~/.quantagent/cache/ (SQLite for time series, JSON for lists).
    TTL: configurable per data type.
    """
    async def get(self, key: str) -> Any | None
    async def set(self, key: str, value: Any, ttl: int = 3600) -> None
    async def invalidate(self, key: str) -> None
    async def clear(self) -> None
```

**Cache policies:**

| Data Type | TTL | Notes |
|---|---|---|
| Universe constituents | 7 days | Updated weekly |
| OHLCV (daily) | 1 hour | Intraday refresh; incremental append for the breadth store |
| Quotes | 15 minutes | Near real-time |
| Fundamentals | 24 hours | Daily refresh |
| Sector performance | 1 hour | Intraday refresh |
| Economic calendar | 12 hours | Updated twice daily |

### 4.3 Batch Provider Methods

Extend `AbstractDataProvider` (see §13 for the full interface delta):

```python
async def get_batch_ohlcv(
    self, symbols: list[str], period: str = "1y", interval: str = "1d"
) -> dict[str, pd.DataFrame]:
    """Fetch OHLCV for multiple symbols efficiently."""

async def get_batch_quotes(self, symbols: list[str]) -> dict[str, dict]:
    """Fetch quotes for multiple symbols efficiently."""
```

Implementation notes:

- **yfinance:** use `yf.download(tickers=[...])` native multi-ticker batching wrapped in `asyncio.to_thread` (per the AGENTS.md async rule for sync SDKs) — do NOT loop N sequential calls.
- **Polygon:** grouped daily bars endpoint where available; otherwise bounded-concurrency `asyncio.TaskGroup`.
- **Alpha Vantage:** no batch support on free tier — sequential with rate-limit backoff, always behind the cache.
- Retrofit `portfolio.py::_fetch_prices` and the screener's sequential loop onto `get_batch_ohlcv`/`get_batch_quotes`.

### 4.4 Shared Paths Helper

**New file:** `quantagent/tools/_paths.py`

`tools/screener.py` and `tools/providers/__init__.py` currently import `quantagent.tui.config`, violating the AGENTS.md dependency rule (`tools/` must not import `tui/`). New modules need `~/.quantagent/` locations (cache, universes, workflows, trades.db). Centralize them in a tiny `tools/_paths.py` (module-level `Path` constants, overridable via env var for tests) instead of deepening the `tui.config` dependency. Migrating the existing violations is optional but recommended.

## 5. Phase 1 — Market-Level Analysis Tools

**Priority:** HIGH | **Effort:** 2-3 weeks | **Dependencies:** Phase 0 (cache + batch fetch)

### 5.1 Sector & Industry Analysis

**New file:** `quantagent/tools/sector_analysis.py`

#### Functions

```python
async def get_sector_performance_ranked(
    provider: AbstractDataProvider,
    periods: list[str] = ["1d", "1w", "1m", "3m", "6m", "1y"],
) -> pd.DataFrame:
    """Rank all GICS sectors by performance across multiple timeframes.
    Returns DataFrame with columns: Sector, 1d%, 1w%, 1m%, 3m%, 6m%, 1y%, Rank.
    Builds on the existing provider.get_sector_performance() (dict), extending
    it with additional timeframes computed from sector ETF OHLCV.
    """

async def get_industry_performance(
    provider: AbstractDataProvider,
    sector: str,
) -> pd.DataFrame:
    """Rank industries within a sector by performance.
    Uses sector ETF constituents or provider industry classification.
    """

async def compute_sector_relative_strength(
    provider: AbstractDataProvider,
    sectors: list[str] | None = None,
    benchmark: str = "SPY",
    period: str = "3m",
) -> pd.DataFrame:
    """Compute relative strength of each sector vs benchmark.
    Returns RS ratio, RS rank, and trend direction (improving/deteriorating/neutral).
    """

async def detect_sector_rotation(
    provider: AbstractDataProvider,
    lookback_days: int = 90,
) -> dict:
    """Detect sector rotation patterns using relative strength momentum.
    Returns: {
        "leading_sectors": [...],
        "lagging_sectors": [...],
        "improving_sectors": [...],
        "deteriorating_sectors": [...],
        "rotation_signal": str,  # "risk-on" | "risk-off" | "neutral"
        "cycle_phase": str,  # "early-recovery" | "mid-expansion" | "late-cycle" | "recession"
    }
    """

async def get_sector_etf_heatmap(
    provider: AbstractDataProvider,
    metric: str = "performance",
) -> dict:
    """Generate heatmap data for sector ETFs.
    metric: "performance" | "volume" | "volatility" | "rsi"
    Returns nested dict suitable for TUI rendering or export.
    """

async def compute_sector_correlation(
    provider: AbstractDataProvider,
    period: str = "6m",
) -> pd.DataFrame:
    """Correlation matrix of sector ETF returns.
    Useful for diversification analysis and regime detection.
    """
```

#### Data Sources

| Provider | Sector Data Available |
|---|---|
| yfinance | Sector ETFs (XLK, XLF, XLE, XLV, XLI, XLC, XLY, XLP, XLU, XLB, XLRE) |
| Alpha Vantage | Sector performance API, industry classification |
| Polygon | Sector/industry classification, group endpoints |

#### Sector ETF Universe (Built-in)

The 11-sector SPDR ETF map already exists as `_SECTOR_ETFS` in `yfinance_provider.py` (and a Polygon twin). Promote it to a single shared constant (e.g., in `tools/universe.py`) instead of duplicating a third copy:

```python
SECTOR_ETFS = {
    "Technology": "XLK",
    "Financials": "XLF",
    "Energy": "XLE",
    "Healthcare": "XLV",
    "Industrials": "XLI",
    "Communication": "XLC",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Utilities": "XLU",
    "Materials": "XLB",
    "Real Estate": "XLRE",
}
```

### 5.2 Market Breadth & Timing Indicators

**New file:** `quantagent/tools/market_breadth.py`

Breadth is split into two tiers (see §5.4 for the rationale):

- **Fast path (index/ETF data only, no universe fetch):** distribution days, Follow-Through Day, VIX regime, sector-ETF %-above-MA proxy. Works instantly on free yfinance.
- **Deep path (universe-level, cache-mandatory):** true A/D line, new highs/lows, % of constituents above MA, breadth thrust. Requires the Phase 0 cache warmed with universe OHLCV.

#### Fast-Path Functions (index data only)

```python
async def count_distribution_days(
    provider: AbstractDataProvider,
    index_symbol: str = "SPY",
    lookback_days: int = 25,
) -> dict:
    """Count IBD-style distribution days (index down >= 0.2% on higher volume
    than prior day) in the lookback window. 5+ in 25 sessions signals
    institutional selling.
    Returns: {"count": int, "dates": [...], "signal": str,  # "healthy" | "caution" | "under-pressure"
    }
    """

async def detect_follow_through_day(
    provider: AbstractDataProvider,
    index_symbol: str = "SPY",
    lookback_days: int = 60,
) -> dict:
    """Detect O'Neil Follow-Through Day: on day 4+ of a rally attempt after a
    correction low, index gains >= 1.25% on higher volume than the prior day.
    Returns: {"ftd_detected": bool, "ftd_date": str | None, "rally_day": int | None,
              "status": str,  # "confirmed-uptrend" | "rally-attempt" | "correction"
    }
    """
```

#### Deep-Path Functions (universe-level, cache-backed)

```python
async def compute_advance_decline(
    provider: AbstractDataProvider,
    universe: str = "sp500",
    period: str = "3m",
) -> pd.DataFrame:
    """Compute advance/decline line for the given universe.
    Returns DataFrame with: Date, Advancing, Declining, Unchanged,
    NetAdvancing, ADLine, ADLine_SMA10, ADLine_SMA20.
    """

async def compute_new_highs_lows(
    provider: AbstractDataProvider,
    universe: str = "sp500",
    period: str = "3m",
) -> pd.DataFrame:
    """Count new 52-week highs and lows per day.
    Returns: Date, NewHighs, NewLows, NetNewHighs, HighLowRatio, HL_SMA10.
    """

async def compute_percent_above_ma(
    provider: AbstractDataProvider,
    universe: str = "sp500",
    ma_periods: list[int] = [10, 20, 50, 200],
) -> dict[int, float]:
    """Percentage of universe members above each moving average.
    Returns {10: 65.2, 20: 58.1, 50: 52.3, 200: 62.8}.
    Fast-path fallback: when the universe cache is cold, compute over the 11
    sector ETFs instead and flag the result as "proxy".
    """

async def compute_breadth_thrust(
    provider: AbstractDataProvider,
    universe: str = "sp500",
    period: str = "3m",
) -> dict:
    """Compute McClellan Breadth Thrust indicator.
    Returns: {
        "thrust_value": float,
        "thrust_signal": str,  # "bullish" | "neutral" | "bearish"
        "history": pd.DataFrame,
    }
    """
```

#### Regime & Sentiment (composite)

```python
async def detect_market_regime(
    provider: AbstractDataProvider,
    universe: str = "sp500",
) -> dict:
    """Composite market regime detection combining cross-asset ratios, trend,
    volatility, and breadth (deep-path breadth when cached, ETF proxies otherwise).

    Cross-asset components (all free ETF tickers — cheap and robust):
      - RSP/SPY: concentration vs broadening
      - IWM/SPY: size factor (risk appetite)
      - XLY/XLP: cyclicals vs defensives
      - SPY/TLT ratio + rolling stock-bond correlation (inflation-regime flag)
      - HYG/LQD: credit risk appetite

    Returns: {
        "regime": str,  # "strong-bull" | "bull" | "neutral" | "bear" | "strong-bear"
        "confidence": float,  # 0.0 - 1.0
        "recommended_exposure": {"min_pct": int, "max_pct": int, "label": str},
        "components": {
            "cross_asset": {"concentration": str, "size": str, "cyclical_defensive": str,
                            "stock_bond": str, "credit": str},
            "breadth_health": str,
            "trend_direction": str,
            "volatility_regime": str,
            "sector_participation": str,
        },
    }
    """

async def compute_market_sentiment(
    provider: AbstractDataProvider,
) -> dict:
    """Composite sentiment score from multiple indicators.
    Returns: {
        "score": float,  # -100 (extreme fear) to +100 (extreme greed)
        "label": str,
        "components": {
            "put_call_ratio": float | None,
            "vix_level": float,
            "vix_term_structure": str,
            "breadth_score": float,
            "momentum_score": float,
        },
    }
    """
```

#### Exposure Guidance

Every composite score maps to an **explicit equity-exposure band** so reports are actionable, not just descriptive. Default mapping (configurable):

| Regime / breadth score | Zone | Recommended exposure |
|---|---|---|
| 80–100 | Strong | 90–100% invested |
| 60–79 | Healthy | 70–90% |
| 40–59 | Neutral | 50–70% |
| 20–39 | Weakening | 40–60% |
| 0–19 | Critical | 25–40% |

`detect_market_regime` and the market report surface `recommended_exposure`; the conviction synthesizer (§8.3) and risk gate (§9.2) consume it.

### 5.3 Market Overview & Heatmap

**New file:** `quantagent/tools/market_overview.py`

#### Functions

```python
async def get_top_movers(
    provider: AbstractDataProvider,
    universe: str = "sp500",
    direction: str = "up",
    count: int = 10,
    period: str = "1d",
) -> pd.DataFrame:
    """Top gainers or losers in the universe.
    direction: "up" | "down"
    Returns: Symbol, Name, Price, Change%, Volume, AvgVolume, Sector.
    """

async def get_most_active(
    provider: AbstractDataProvider,
    universe: str = "sp500",
    count: int = 10,
) -> pd.DataFrame:
    """Most active stocks by volume.
    Returns: Symbol, Name, Price, Change%, Volume, AvgVolumeRatio.
    """

async def generate_market_heatmap(
    provider: AbstractDataProvider,
    universe: str = "sp500",
    metric: str = "performance",
    group_by: str = "sector",
) -> dict:
    """Generate hierarchical heatmap data grouped by sector/industry.
    metric: "performance" | "volume" | "volatility" | "rsi" | "market_cap"
    Returns nested dict: {sector: {industry: {symbol: {value, size}}}}
    """

async def get_market_summary(
    provider: AbstractDataProvider,
) -> dict:
    """One-shot market overview combining key indices, breadth, and sentiment.
    Fast path only: indices, sector ETFs, distribution days, FTD status,
    cross-asset regime, VIX — no universe fetch, so it always completes in seconds.
    Returns: {
        "indices": {symbol: {price, change%, trend}},
        "breadth": {distribution_days, ftd_status, pct_above_ma_proxy},
        "sentiment": {score, label},
        "regime": str,
        "recommended_exposure": {...},
        "key_levels": {support, resistance},
    }
    """

async def get_economic_calendar(
    provider: AbstractDataProvider,
    days_ahead: int = 7,
    impact: str = "high",
) -> pd.DataFrame:
    """Upcoming economic events.
    impact: "high" | "medium" | "low" | "all"
    Returns: Date, Time, Event, Consensus, Previous, Impact.
    """
```

### 5.4 Implementation Approach: Fast Path vs Deep Path

1. **Fast path first.** `/market`, regime detection, and the daily report must work on free yfinance with ~15 tickers (indices, sector ETFs, cross-asset ETFs, VIX) and no cache warm-up. This is the default execution path and always completes within the tool timeout.
2. **Deep path is cache-mandatory.** Universe-level breadth reads from an incremental SQLite store (`~/.quantagent/cache/breadth.db`). On cold cache, deep-path tools return the ETF-proxy fallback plus a note that full breadth is warming; a background/explicit warm-up task (batch `get_batch_ohlcv` via Phase 0) populates the store, after which daily updates are incremental (one day of data per symbol).
3. **Universe management:** cache constituent lists locally (`~/.quantagent/cache/universes/`), update weekly.
4. **Batch data fetching:** always via `get_batch_ohlcv` (yfinance multi-ticker download in `asyncio.to_thread`); bounded-concurrency `asyncio.TaskGroup` fallback for providers without batch support, with rate limiting.
5. **Paid providers as accelerators:** Polygon grouped daily bars can warm the whole universe in a few calls; the design must not require it.

## 6. Phase 2 — Advanced Screening

**Priority:** HIGH | **Effort:** 2 weeks | **Dependencies:** Phase 0 (batch + tests), Phase 1 (sector data)

### 6.1 Enhanced Screener

**Extend:** `quantagent/tools/screener.py`

Prerequisites from Phase 0: baseline tests exist, RSI no-op resolved. Additionally, this phase must **lift the 100-symbol cap** and replace the sequential per-ticker fetch with `get_batch_quotes`/`get_batch_ohlcv` — otherwise full-universe technical screens cannot meet the §18 targets.

#### New Functions

```python
async def screen_by_technicals(
    provider: AbstractDataProvider,
    criteria: dict[str, Any],
    universe: str = "sp500",
) -> pd.DataFrame:
    """Screen by technical criteria.
    Supported criteria keys:
      - "rsi_lt": float (RSI below)
      - "rsi_gt": float (RSI above)
      - "macd_bullish": bool (MACD line > signal)
      - "price_above_sma": int (period)
      - "price_below_sma": int (period)
      - "volume_expansion": float (ratio vs avg)
      - "atr_breakout": bool (price > upper BB)
      - "adx_gt": float (trend strength above)
    """

async def screen_by_fundamentals(
    provider: AbstractDataProvider,
    criteria: dict[str, Any],
    universe: str = "sp500",
) -> pd.DataFrame:
    """Screen by fundamental criteria.
    Supported criteria keys:
      - "pe_lt" / "pe_gt": float
      - "pb_lt" / "pb_gt": float
      - "roe_gt": float
      - "roa_gt": float
      - "debt_equity_lt": float
      - "dividend_yield_gt": float
      - "revenue_growth_gt": float
      - "eps_growth_gt": float
      - "market_cap_gt" / "market_cap_lt": float
      - "piotroski_f_gt": int (0-9)
    """

async def screen_combined(
    provider: AbstractDataProvider,
    technical_criteria: dict[str, Any] | None = None,
    fundamental_criteria: dict[str, Any] | None = None,
    universe: str = "sp500",
) -> pd.DataFrame:
    """Screen by combined technical + fundamental criteria.
    Applies both filters and returns intersection.
    Pre-filters by cheap fundamental criteria first, then computes
    expensive technicals only on survivors.
    """

async def screen_vcp_pattern(
    provider: AbstractDataProvider,
    universe: str = "sp500",
    max_contraction_pct: float = 0.50,
    min_prior_advance_pct: float = 0.30,
) -> pd.DataFrame:
    """Screen for Volatility Contraction Pattern (Minervini).
    Criteria: prior advance > 30%, contraction depth < 50%,
    tightening price action, volume dry-up, above 200 SMA.
    """

async def screen_breakout_candidates(
    provider: AbstractDataProvider,
    universe: str = "sp500",
    proximity_to_high_pct: float = 0.05,
    volume_ratio_min: float = 1.5,
) -> pd.DataFrame:
    """Screen for stocks near 52-week highs with volume expansion.
    """

async def screen_oversold_reversal(
    provider: AbstractDataProvider,
    universe: str = "sp500",
    rsi_threshold: float = 30.0,
    min_decline_pct: float = 0.20,
) -> pd.DataFrame:
    """Screen for oversold reversal candidates.
    RSI < threshold, price declined > min_decline from recent high,
    showing bullish divergence or hammer pattern.
    """
```

### 6.2 Custom Universe Support

**New file:** `quantagent/tools/universe.py`

```python
BUILTIN_UNIVERSES = ["sp500", "nasdaq100", "dow30", "sector_etfs"]
# NOTE: russell2000 intentionally excluded — no free, reliable constituent
# source. Reintroduce gated on a paid provider (FMP/Polygon) in Phase 6.

def list_universes() -> list[str]:
    """List all available universes (built-in + custom)."""

def create_universe(name: str, symbols: list[str]) -> None:
    """Save a custom universe to ~/.quantagent/universes/<name>.json."""

def load_universe(name: str) -> list[str]:
    """Load a universe by name. Built-in or custom."""

def delete_universe(name: str) -> None:
    """Delete a custom universe."""

def get_universe_metadata(name: str) -> dict:
    """Return universe metadata: symbol count, creation date, last updated."""
```

**Storage:** `~/.quantagent/universes/<name>.json` (path from `tools/_paths.py`). `sp500`/`nasdaq100` keep the existing Wikipedia scraping (moved here from `screener.py`), `dow30` adds its Wikipedia page, `sector_etfs` reuses the shared `SECTOR_ETFS` constant. Constituent lists are cached per the §4.2 policy — Wikipedia scraping is fragile, so a stale cached list is preferred over a hard failure.

## 7. Phase 3 — Report Generation

**Priority:** MEDIUM | **Effort:** 2-3 weeks | **Dependencies:** Phases 1-2

**New dependencies:** `jinja2` (templates); `weasyprint` optional extra for PDF export. Neither is currently in `pyproject.toml`.

### 7.1 Report Framework

**New directory:** `quantagent/tools/reports/`

```
reports/
├── __init__.py
├── base.py              # ReportGenerator base class, ReportConfig model
├── market_report.py     # Daily/weekly market overview report
├── sector_report.py     # Sector analysis report
├── stock_report.py      # Individual stock deep-dive report
├── portfolio_report.py  # Portfolio performance & risk report
├── screening_report.py  # Screening results report
└── templates/
    ├── market_daily.md.j2
    ├── market_weekly.md.j2
    ├── sector_analysis.md.j2
    ├── stock_deep_dive.md.j2
    ├── portfolio_review.md.j2
    └── screening_results.md.j2
```

### 7.2 Report Types

#### Market Daily Brief

```python
async def generate_market_daily(
    provider: AbstractDataProvider,
    config: ReportConfig | None = None,
) -> Report:
    """Generate daily market brief.
    Sections:
    1. Market Overview — indices, key levels
    2. Market Regime — current regime + confidence + recommended exposure band
    3. Timing Signals — distribution-day count, FTD status
    4. Breadth — A/D line, new highs/lows, % above MAs (or ETF proxy on cold cache)
    5. Sector Performance — ranked table + heatmap
    6. Top Movers — gainers, losers, most active
    7. Economic Calendar — upcoming events
    8. Sentiment — composite score + components
    """
```

#### Sector Deep-Dive

```python
async def generate_sector_report(
    provider: AbstractDataProvider,
    sector: str,
    config: ReportConfig | None = None,
) -> Report:
    """Generate sector analysis report.
    Sections:
    1. Sector Overview — performance across timeframes
    2. Industry Breakdown — ranked industries
    3. Key Stocks — top performers, most active
    4. Relative Strength — vs benchmark, trend
    5. Technical Summary — sector ETF indicators
    6. Rotation Context — where this sector fits in cycle
    """
```

#### Stock Deep-Dive

```python
async def generate_stock_report(
    provider: AbstractDataProvider,
    symbol: str,
    config: ReportConfig | None = None,
) -> Report:
    """Generate comprehensive stock report.
    Sections:
    1. Company Overview — sector, industry, market cap, description
    2. Technical Analysis — indicators, patterns, support/resistance, signals
    3. Fundamental Analysis — key metrics, DCF, F-Score, Z-Score
    4. Peer Comparison — vs sector/industry peers
    5. Recent News — last 7 days
    6. Backtest Summary — best strategy performance (if configured)
    7. Verdict — stance, conviction, actionable levels
    """
```

#### Portfolio Review

```python
async def generate_portfolio_report(
    provider: AbstractDataProvider,
    symbols: list[str],
    weights: dict[str, float] | None = None,
    config: ReportConfig | None = None,
) -> Report:
    """Generate portfolio review report.
    Sections:
    1. Portfolio Summary — allocation, total value, P&L
    2. Risk Metrics — beta, VaR, CVaR, Sharpe, max drawdown
    3. Sector Exposure — breakdown by sector
    4. Individual Positions — per-stock analysis
    5. Optimization Suggestions — recommended rebalancing
    6. Monte Carlo — simulation results
    """
```

### 7.3 Report Model

```python
class ReportConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    title: str = ""
    format: str = "markdown"  # "markdown" | "html" | "pdf"
    include_charts: bool = False
    date_range: str = "1y"
    benchmark: str = "SPY"

class Report(BaseModel):
    model_config = ConfigDict(frozen=True)
    title: str
    generated_at: datetime
    sections: list[ReportSection]
    metadata: dict[str, Any]

class ReportSection(BaseModel):
    # arbitrary_types_allowed required for pd.DataFrame fields
    # (precedent: BacktestResult in tools/backtesting.py)
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
    title: str
    content: str  # Markdown content
    tables: list[pd.DataFrame] = Field(default_factory=list)
    charts_data: list[dict] = Field(default_factory=list)
```

### 7.4 Export Functions

```python
def export_report_markdown(report: Report, path: Path) -> None:
    """Export report as Markdown file."""

def export_report_html(report: Report, path: Path) -> None:
    """Export report as styled HTML file."""

def export_report_pdf(report: Report, path: Path) -> None:
    """Export report as PDF (requires the optional weasyprint extra)."""
```

## 8. Phase 4 — Workflow & Automation

**Priority:** MEDIUM | **Effort:** 2 weeks | **Dependencies:** Phases 1-3

**New dependency:** `pyyaml` (custom workflow files; only `toml` is currently available).

### 8.1 Workflow System

**New file:** `quantagent/tools/workflows.py`

```python
class WorkflowStep(BaseModel):
    model_config = ConfigDict(frozen=True)
    tool_name: str
    parameters: dict[str, Any]
    output_key: str  # store result for downstream steps

class Workflow(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    description: str
    steps: list[WorkflowStep]
    estimated_duration: str  # e.g. "2-3 minutes"

class WorkflowResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    workflow_name: str
    completed_at: datetime
    step_results: dict[str, Any]
    summary: str
```

#### Built-in Workflows

```python
def daily_market_check() -> Workflow:
    """15-minute daily market review.
    Steps: market summary -> regime detection -> timing signals (distribution
    days, FTD) -> breadth -> sector performance -> top movers ->
    conviction synthesis (capstone: one score + exposure recommendation).
    """

def weekly_sector_review() -> Workflow:
    """Weekly sector rotation analysis.
    Steps: sector ranking -> relative strength -> rotation detection -> sector deep-dives (top 3).
    """

def stock_research(symbol: str) -> Workflow:
    """Deep-dive stock research.
    Steps: quote -> technicals -> fundamentals -> peer comparison -> news -> verdict.
    """

def screening_pipeline(criteria: dict) -> Workflow:
    """Screen + analyze top candidates.
    Steps: screen -> rank -> analyze top 5 -> generate report.
    """

def portfolio_rebalance_review(symbols: list[str]) -> Workflow:
    """Portfolio health check.
    Steps: current allocation -> risk metrics -> optimization -> rebalancing suggestions.
    """
```

### 8.2 Custom Workflows

Users can define custom workflows in `~/.quantagent/workflows/<name>.yaml`:

```yaml
name: my_morning_routine
description: "My personal morning market review"
steps:
  - tool: get_market_summary
    parameters: {}
    output_key: market
  - tool: detect_market_regime
    parameters: {}
    output_key: regime
  - tool: get_sector_performance_ranked
    parameters:
      periods: ["1d", "1w", "1m"]
    output_key: sectors
  - tool: screen_oversold_reversal
    parameters:
      rsi_threshold: 35
    output_key: candidates
```

### 8.3 Conviction Synthesizer

**New file:** `quantagent/tools/conviction.py`

Adopted from claude-trading-skills' Druckenmiller-style synthesizer: a meta-tool that fuses the market-level sub-analyses into one score, with an explicit reward for **signal convergence** (independent signals agreeing is worth more than any single strong signal).

```python
async def synthesize_conviction(
    provider: AbstractDataProvider,
    universe: str = "sp500",
) -> dict:
    """Fuse regime, breadth, timing, sector rotation, and sentiment into a
    composite conviction score.

    Components (weighted): market regime, breadth health, timing signals
    (FTD/distribution days), sector rotation posture, sentiment, and a
    signal-convergence bonus (agreement across independent components).

    Returns: {
        "conviction_score": float,  # 0-100
        "stance": str,  # "aggressive" | "constructive" | "selective" | "defensive" | "risk-off"
        "recommended_exposure": {"min_pct": int, "max_pct": int, "label": str},
        "components": {name: {"score": float, "weight": float, "signal": str}},
        "convergence": {"agreeing": int, "total": int, "bonus": float},
        "key_risks": [...],
    }
    """
```

This is the capstone step of `daily_market_check` and a required input to the pre-trade discipline gate (§9.2).

## 9. Phase 5 — Trade Journal & Risk Discipline

**Priority:** LOW | **Effort:** 2 weeks | **Dependencies:** Phase 1 (regime, for the discipline gate)

### 9.1 Trade Journal

**New file:** `quantagent/tools/trade_journal.py`

The journal adopts claude-trading-skills' **forward-only lifecycle** — status can only move forward (`idea → entry_ready → active → partially_closed → closed | invalidated`), preventing retroactive tampering — and captures **MAE/MFE** (maximum adverse/favorable excursion) on close for postmortem quality analysis.

```python
class TradeIdea(BaseModel):
    id: str
    symbol: str
    thesis: str
    entry_plan: str
    target: float | None = None
    stop: float | None = None
    status: str = "idea"  # "idea" | "entry_ready" | "active" | "partially_closed" | "closed" | "invalidated"
    created_at: datetime
    closed_at: datetime | None = None
    outcome: str | None = None
    mae_pct: float | None = None  # max adverse excursion while open
    mfe_pct: float | None = None  # max favorable excursion while open
    realized_pnl_pct: float | None = None
    notes: list[str] = Field(default_factory=list)

async def log_trade_idea(
    symbol: str,
    thesis: str,
    entry_plan: str,
    target: float | None = None,
    stop: float | None = None,
) -> TradeIdea:
    """Log a new trade idea to the journal."""

async def update_trade_status(
    trade_id: str,
    status: str,
    notes: str | None = None,
) -> None:
    """Advance trade status (forward-only; rejects backward transitions) and add notes."""

async def close_trade(
    provider: AbstractDataProvider,
    trade_id: str,
    exit_price: float,
    outcome_notes: str | None = None,
) -> dict:
    """Close a trade, record outcome, and compute MAE/MFE from OHLCV over the
    holding period."""

async def get_open_trades() -> list[TradeIdea]:
    """List all open trade ideas."""

async def get_trade_history(
    days: int = 30,
    status: str | None = None,
) -> list[TradeIdea]:
    """Get trade history with optional filters."""

async def compute_trade_stats() -> dict:
    """Compute journal statistics.
    Returns: {
        "total_trades": int,
        "win_rate": float,
        "avg_win": float,
        "avg_loss": float,
        "profit_factor": float,
        "expectancy": float,
        "max_consecutive_losses": int,
        "avg_mae": float,
        "avg_mfe": float,
    }
    """
```

**Storage:** SQLite at `~/.quantagent/trades.db` (path from `tools/_paths.py`)

### 9.2 Risk-Gating Stack

**New file:** `quantagent/tools/risk_gate.py`

Adopted from claude-trading-skills' behavioral-risk layer. Both gates emit **recommendations** (they never touch a broker) and are surfaced by the agent before trade-planning conversations.

#### Drawdown Circuit Breaker

Reads realized P&L from the trade journal and gates new-entry recommendations:

```python
class CircuitBreakerConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    daily_loss_limit_pct: float = 2.0
    weekly_loss_limit_pct: float = 5.0
    monthly_loss_limit_pct: float = 8.0
    consecutive_loss_cooldown: int = 2  # losers in a row -> 24h cooldown

async def check_circuit_breaker(
    config: CircuitBreakerConfig | None = None,
) -> dict:
    """Evaluate journal P&L against loss limits.
    Returns: {
        "state": str,  # "trading_allowed" | "cooldown" | "halted"
        "triggered_rules": [...],
        "cooldown_until": datetime | None,
        "period_pnl": {"daily_pct": float, "weekly_pct": float, "monthly_pct": float},
    }
    """
```

#### Pre-Trade Discipline Gate

A checklist gate evaluated before any new trade idea is logged as `entry_ready`:

```python
async def check_discipline_gate(
    provider: AbstractDataProvider,
    trade_id: str,
) -> dict:
    """Validate a trade idea against discipline rules.
    Blocks (returns "blocked") when:
      - no written thesis or entry plan
      - no predefined stop
      - position size exceeds plan limits
      - circuit breaker is in cooldown/halted state
      - market regime recommends reduce-only (regime "bear"/"strong-bear")
    Returns: {"result": str,  # "pass" | "warnings" | "blocked"
              "checks": {name: {"passed": bool, "detail": str}}}
    """
```

## 10. Phase 6 — Additional Enhancements

**Priority:** LOW | **Effort:** Ongoing

### 10.1 New Data Providers

| Provider | Key Required | Best For | Status |
|---|---|---|---|
| **FMP** (Financial Modeling Prep) | Yes | Fundamentals (real Piotroski), economic calendar, batch data, constituents | Deferred — no API key yet |
| **Alpaca** | Yes | Portfolio integration (read-only positions) | Deferred — needs broker account |
| **FINVIZ** | No (scraping) | Screening, sentiment | Dropped — fragile scraping, ToS risk; local screener covers it |

Adding FMP or Polygon-backed constituents is the trigger to reintroduce `russell2000` as a screening universe (§6.2).

### 10.2 Advanced Analysis Modules

**New file:** `quantagent/tools/pair_trading.py`

```python
async def find_cointegrated_pairs(
    provider: AbstractDataProvider,
    universe: str = "sp500",
    sector: str | None = None,
) -> list[dict]:
    """Find cointegrated stock pairs for statistical arbitrage."""

async def compute_spread_metrics(
    provider: AbstractDataProvider,
    symbol_a: str,
    symbol_b: str,
) -> dict:
    """Compute spread metrics for a pair: half-life, z-score, hedge ratio."""
```

**New file:** `quantagent/tools/event_analysis.py`

```python
async def analyze_earnings_impact(
    provider: AbstractDataProvider,
    symbol: str,
    quarters: int = 8,
) -> dict:
    """Analyze historical price reactions to earnings."""

async def get_earnings_calendar_range(
    provider: AbstractDataProvider,
    start_date: str,
    end_date: str,
    universe: str | None = None,
) -> pd.DataFrame:
    """Get earnings calendar for a date range, optionally filtered by universe."""
```

## 11. New Skills

Skills live at the **repo root `skills/`** directory (see `agent/skills.py::BUILTIN_SKILLS_DIR`), not inside `quantagent/`. Each is a directory with a `SKILL.md` (frontmatter: `name`, `description`, `allowed-tools`) plus optional reference files, following the 5 existing skills. Note `strategy-patterns/regime_matrix.md` already contains regime methodology worth folding into `market-regime/`.

| Skill Directory | Description | Trigger |
|---|---|---|
| `skills/market-regime/` | Market regime detection methodology (cross-asset ratios + breadth) | "What is the current market regime?" |
| `skills/sector-rotation/` | Sector rotation analysis and cycle positioning | "Analyze sector rotation" |
| `skills/market-breadth/` | Breadth + timing-signal interpretation (A/D, FTD, distribution days) | "Analyze market breadth" |
| `skills/exposure-discipline/` | Exposure bands, circuit breaker, and discipline-gate methodology | "How much should I be invested?" / trade-planning prompts |
| `skills/advanced-screening/` | Multi-factor screening methodology | "Screen for..." with complex criteria |
| `skills/report-generation/` | Report templates and formatting rules | "Generate a report" |

## 12. New TUI Commands

Existing analysis commands (`/analyze`, `/screen`, `/backtest`, `/compare`) are thin handlers in `tui/commands.py` that forward a natural-language prompt to the agent via `app._submit_user_message(...)` — they do not call tools directly. New commands follow the same pattern.

| Command | Purpose |
|---|---|
| `/market` | Market overview (regime, timing signals, breadth, sentiment, exposure) |
| `/sector [name]` | Sector analysis (all sectors or specific) |
| `/screen <criteria>` | Enhanced screening (extended syntax) |
| `/heatmap [metric]` | Market heatmap visualization |
| `/report <type> [args]` | Generate report (market/sector/stock/portfolio) |
| `/workflow <name>` | Run a predefined workflow |
| `/workflows` | List available workflows |
| `/journal` | View trade journal |
| `/journal add <symbol> <thesis>` | Log a trade idea |
| `/riskgate` | Show circuit-breaker state and discipline-gate summary |
| `/universe <name>` | Switch active screening universe |
| `/universes` | List available universes |

## 13. AbstractDataProvider Changes

### 13.1 Already Exists (no change or minor extension)

These methods are already abstract on `AbstractDataProvider` (`tools/providers/base.py`) and implemented by all 3 providers — the original draft of this spec incorrectly listed some as new:

```python
async def get_ohlcv(symbol, period="1y", interval="1d") -> pd.DataFrame
async def get_quote(symbol) -> dict
async def get_fundamentals(symbol) -> dict
async def search_symbols(query) -> list[dict]
async def get_news(symbol, days=7) -> list[dict]
async def get_earnings_calendar(symbol, lookahead_days=90) -> list[dict]
async def get_sector_performance() -> dict   # stays dict; sector_analysis.py
                                             # builds its ranked DataFrame on top
async def get_economic_indicators() -> dict
```

`get_sector_performance` keeps its existing `dict` return type — changing it to a DataFrame would break the existing tool and all 3 providers for no benefit; `get_sector_performance_ranked` (§5.1) provides the DataFrame view at the tools layer.

### 13.2 New Methods

```python
class AbstractDataProvider:
    async def get_universe_symbols(self, universe: str) -> list[str]:
        """Return list of symbols in a named universe.
        Default implementation delegates to tools/universe.py (Wikipedia/cache);
        providers with native constituent endpoints (Polygon, future FMP) override.
        """

    async def get_batch_ohlcv(
        self, symbols: list[str], period: str = "1y", interval: str = "1d"
    ) -> dict[str, pd.DataFrame]:
        """Fetch OHLCV for multiple symbols efficiently.
        yfinance: yf.download(tickers=[...]) in asyncio.to_thread.
        Default implementation: bounded-concurrency loop over get_ohlcv."""

    async def get_batch_quotes(self, symbols: list[str]) -> dict[str, dict]:
        """Fetch quotes for multiple symbols efficiently."""

    async def get_industry_classification(self, symbol: str) -> dict:
        """Return sector and industry for a symbol (normalized across providers)."""

    async def get_economic_events(
        self, days_ahead: int = 7
    ) -> list[dict]:
        """Return upcoming economic events."""
```

To avoid breaking the ABC contract for all providers at once, add the new methods as **concrete default implementations** on the base class (delegating to per-symbol methods / universe helpers) rather than new abstractmethods; providers override where a native batch endpoint exists.

## 14. Architecture Changes

### 14.1 New Module Structure

```
quantagent/tools/
├── _paths.py               # NEW (Phase 0) — shared ~/.quantagent paths
├── cache.py                # NEW (Phase 0)
├── market_data.py          # EXTEND with new provider wrappers
├── technical.py            # Fix buy_and_hold; otherwise unchanged
├── fundamental.py          # Unchanged
├── backtesting.py          # Unchanged
├── portfolio.py            # Retrofit onto get_batch_ohlcv
├── screener.py             # FIX (Phase 0) + EXTEND with advanced screening
├── sector_analysis.py      # NEW
├── market_breadth.py       # NEW (incl. FTD / distribution days)
├── market_overview.py      # NEW
├── conviction.py           # NEW (Phase 4)
├── universe.py             # NEW
├── workflows.py            # NEW
├── trade_journal.py        # NEW
├── risk_gate.py            # NEW (Phase 5)
├── pair_trading.py         # NEW (Phase 6)
├── event_analysis.py       # NEW (Phase 6)
├── reports/                # NEW
│   ├── __init__.py
│   ├── base.py
│   ├── market_report.py
│   ├── sector_report.py
│   ├── stock_report.py
│   ├── portfolio_report.py
│   └── templates/
└── providers/
    ├── base.py             # EXTEND with new methods (concrete defaults)
    ├── yfinance_provider.py  # EXTEND (batch via yf.download)
    ├── alpha_vantage.py      # EXTEND
    └── polygon.py            # EXTEND (grouped daily bars)
```

### 14.2 Agent Tool Registry Integration

New market-analysis functions are exposed to the agent via `agent/tools_registry.py`, which imposes conventions the tools layer must anticipate (~15 new agent tools across the phases):

- Registry wrappers are bare `async def _name(provider, ...)` functions bound with `_bind_provider(...)`; the Google-style **docstring is the LLM interface** and must document parameters and defaults precisely.
- Wrappers return **strings** (JSON via `_json_dumps`, or markdown tables) — the DataFrame/dict returns specified in this document are the `tools/` layer contract; each registry wrapper serializes.
- No try/except inside tools — `ErrorLoggingMiddleware` handles errors.
- Every wrapper runs under `_with_timeout(...)` with `_TOOL_TIMEOUT_SEC = 30`. **This is too tight for cold-cache universe operations.** Add a per-tool timeout override to `_with_timeout` (e.g., 120s for deep-path breadth and full-universe screens); fast-path tools keep 30s. The fast-path/deep-path split (§5.4) exists precisely so the default experience never waits on a cold cache.

### 14.3 Tool Progress Channel

Long-running tools (workflows, breadth warm-up, universe screens,
reports) report live progress to the TUI through a dependency-clean
channel: `utils/progress.py` holds a sink + a call-id contextvar;
`ToolProgressMiddleware` (agent layer) binds the active tool-call id
around each tool invocation; `AgentRunner` (adapter) installs a sink
that enqueues `ToolProgress` events; the TUI rewrites the running tool
line in place (`● run_workflow_tool — step 2/4: sectors…`). Tools call
`report_progress(text)` — a no-op outside the app.

### 14.4 Dependency Rules

Target rules are unchanged (`tools/` must not import `tui/`, `agent/`, or `adapter/`). However, `tools/screener.py` and `tools/providers/__init__.py` **already violate** this by importing `quantagent.tui.config`. New modules must not deepen the violation: all `~/.quantagent/` paths come from `tools/_paths.py` (§4.4), and any config values tools need are passed as function parameters. Migrating the existing violations is a recommended (non-blocking) Phase 0 cleanup.

### 14.5 New Dependencies

| Dependency | Phase | Purpose |
|---|---|---|
| `jinja2` | 3 | Report templates |
| `pyyaml` | 4 | Custom workflow files (only `toml` is present today) |
| `weasyprint` (optional extra) | 3 | PDF export |

All new code follows AGENTS.md: `from __future__ import annotations`, full type annotations (mypy `disallow_untyped_defs`), Google-style docstrings, ruff cognitive-complexity < 5 (decompose into `_dispatch`-style helpers), async for I/O / sync for CPU-bound (`asyncio.to_thread` if >100ms), frozen Pydantic result models, no hardcoded secrets.

## 15. Implementation Order & Milestones

### Milestone 0: Prerequisites & Fixes (Days 1-4)

- [x] Fix RSI screening no-op, `buy_and_hold` gap, `russell2000` phantom universe
- [x] Add `tests/unit/tools/test_screener.py` baseline tests
- [x] Implement `tools/_paths.py`
- [x] Implement `DataCache` (`tools/cache.py`)
- [x] Add `get_batch_ohlcv` / `get_batch_quotes` (base defaults + yfinance batch impl)
- [x] Retrofit `portfolio.py::_fetch_prices` and screener fetch onto batch methods
- [x] Add per-tool timeout override in `agent/tools_registry.py`

### Milestone 1: Market Fast Path (Week 1-2)

- [x] Implement `sector_analysis.py` (all functions)
- [x] Implement `market_breadth.py` fast path: distribution days, FTD, ETF-proxy % above MA
- [x] Implement `detect_market_regime` (cross-asset ratios + ETF proxies) with `recommended_exposure`
- [x] Implement `market_overview.py::get_market_summary` (fast path only)
- [x] Extend providers with `get_industry_classification`
- [x] Add `market-regime` and `sector-rotation` skills
- [x] Add `/market` and `/sector` TUI commands
- [x] Unit tests for all new tools (85%+ coverage)

### Milestone 2: Universe Breadth (Deep Path) (Week 3)

- [x] Incremental breadth store (`~/.quantagent/cache/breadth.db`) + warm-up task
- [x] `compute_advance_decline`, `compute_new_highs_lows`, `compute_percent_above_ma` (universe), `compute_breadth_thrust`
- [x] Wire deep-path breadth into `detect_market_regime` when cache is warm
- [x] `compute_market_sentiment`, remaining `market_overview.py` functions
- [x] Add `market-breadth` skill
- [x] Unit tests

### Milestone 3: Advanced Screening (Week 4)

- [x] Lift 100-symbol cap; batch-fetch screening rows
- [x] Extend `screener.py` with new screening functions
- [x] Implement `universe.py` (custom universe support; move Wikipedia scraping here)
- [x] Add `advanced-screening` skill
- [x] Extend `/screen` command with new syntax
- [x] Add `/universe` and `/universes` commands
- [x] Unit tests for all new screening functions

### Milestone 4: Reports (Week 5-6)

- [x] Add `jinja2` dependency; implement report framework (`reports/base.py`)
- [x] Implement all report generators
- [x] Create Jinja2 templates for each report type
- [x] Implement export functions (Markdown, HTML; PDF as optional extra)
- [x] Add `report-generation` skill
- [x] Add `/report` command
- [x] Unit tests for report generation

### Milestone 5: Workflows & Conviction (Week 7)

- [x] Add `pyyaml` dependency; implement `workflows.py` (workflow engine)
- [x] Define all built-in workflows
- [x] Implement `conviction.py` synthesizer; wire as `daily_market_check` capstone
- [x] Support custom workflow YAML loading
- [x] Add `/workflow` and `/workflows` commands
- [x] Unit tests for workflow execution and conviction scoring

### Milestone 6: Trade Journal & Risk Discipline (Week 8)

- [x] Implement `trade_journal.py` (forward-only lifecycle, MAE/MFE)
- [x] Create SQLite schema for trades
- [x] Implement `risk_gate.py` (circuit breaker + discipline gate)
- [x] Add `exposure-discipline` skill
- [x] Add `/journal` and `/riskgate` commands
- [x] Unit tests

### Milestone 7: Polish & Advanced (Week 9+)

- [x] Pair trading module (`tools/pair_trading.py` — cointegration scan + spread metrics)
- [x] Event analysis module (`tools/event_analysis.py` — earnings impact + calendar range)
- [x] Performance optimization (batch fetching, caching — delivered in Milestones 0-2)
- [x] Documentation updates
- [ ] **FMP provider — DEFERRED** (no API key yet; still gates real Piotroski
  screening, the economic calendar, and `russell2000` constituents)
- [ ] **Alpaca portfolio integration — DEFERRED** (requires a broker account)
- ~~FINVIZ provider~~ — **DROPPED**: scraping is fragile and against FINVIZ
  ToS without Elite; the local screener covers the same ground

## 16. Comparison with claude-trading-skills

| Aspect | claude-trading-skills | QuantAgent (planned) |
|---|---|---|
| **Interface** | Claude Code skills (markdown instructions) | Python tools + TUI + agent |
| **Execution** | LLM reads skills, calls external tools | Agent calls Python functions directly |
| **Data** | External APIs (FMP, Alpaca), precomputed public CSVs | Provider abstraction with 3+ backends, local cache |
| **Market Analysis** | Breadth via precomputed CSV, chart image analysis | Programmatic computation from OHLCV data (fast path + cached deep path) |
| **Screening** | FMP API-based screeners | Local computation with provider data |
| **Workflows** | YAML skill sequences | Python workflow engine + YAML custom |
| **Reports** | Markdown generation by LLM | Structured reports with templates + export |
| **Trade Memory** | YAML thesis files, forward-only lifecycle | SQLite journal adopting the same lifecycle + MAE/MFE |
| **Risk Discipline** | Circuit breaker + discipline gate skills | Same stack as Python tools (`risk_gate.py`) |
| **Reports Export** | Markdown only | Markdown, HTML, PDF |

**Key advantages of QuantAgent approach:**
- Real-time data via provider abstraction (no manual CSV uploads)
- Programmatic computation (not dependent on LLM reasoning for math)
- TUI for interactive exploration
- Existing backtesting engine with vectorbt
- Structured event architecture for reliable UI updates

**Concepts adopted from claude-trading-skills** (now in scope, see §1): cross-asset regime detection, breadth composite scoring with exposure bands, FTD/distribution-day timing, conviction synthesis with signal convergence, workflow composition, forward-only trade journaling with MAE/MFE, drawdown circuit breaker + pre-trade discipline gate.

**Acknowledged but not adopted:** their precomputed-public-CSV data strategy (we compute locally with caching instead — same zero-cost goal, no dependency on a third party's published data); the `edge-*` automated strategy-R&D pipeline (interesting future direction — QuantAgent's backtester + walk-forward is the natural substrate); options analysis and short-side screeners (out of scope for now).

## 17. Risk & Considerations

| Risk | Mitigation |
|---|---|
| API rate limits for batch operations | DataCache + sequential fallback with backoff |
| 30s agent tool timeout vs universe-scale operations | Fast-path/deep-path split; per-tool timeout override; cache-first design |
| Wikipedia constituent scraping is fragile | Cache constituents (7-day TTL); serve stale cache over hard failure; provider-native constituents in Phase 6 |
| Large data volumes for universe-level analysis | Batch fetching, incremental computation, SQLite storage |
| Provider inconsistency in sector/industry classification | Normalize classifications in provider adapters |
| Performance degradation with many symbols | Parallel fetching via TaskGroup, caching, lazy loading |
| Complex screening criteria performance | Pre-filter by cheap criteria first, then expensive ones |
| Report template maintenance | Keep templates simple, use Jinja2 inheritance |
| `tools/` → `tui/` dependency creep | `tools/_paths.py` + parameter passing; no new `tui.config` imports in tools |

## 18. Success Metrics

Latency targets are qualified by cache state — cold-cache universe operations are explicitly allowed to be slow (they warm the cache); the default user experience runs on the fast path or a warm cache.

| Metric | Target |
|---|---|
| Market overview (`/market`, fast path) | < 15 seconds, no cache required |
| Market regime detection (fast path) | < 15 seconds |
| Sector analysis generation time | < 20 seconds |
| Universe breadth (warm cache, incremental update) | < 10 seconds |
| Universe breadth (cold cache warm-up) | < 10 minutes, runs once, reports progress |
| Full stock report generation time | < 45 seconds |
| Screening (S&P 500 universe, warm cache) | < 60 seconds |
| Report export (Markdown) | < 5 seconds |
| Cache hit rate for daily operations | > 60% |
| New tool test coverage | >= 85% |

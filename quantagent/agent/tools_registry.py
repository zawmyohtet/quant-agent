"""LangChain @tool wrappers for all quant tools."""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
from datetime import UTC, datetime
from typing import Any

from langchain.tools import tool

from quantagent.tools._paths import reports_dir
from quantagent.tools.backtesting import BacktestConfig, format_backtest_result, run_backtest
from quantagent.tools.breadth_store import BreadthStore
from quantagent.tools.conviction import synthesize_conviction
from quantagent.tools.event_analysis import (
    analyze_earnings_impact,
    get_earnings_calendar_range,
)
from quantagent.tools.fundamental import (
    compute_dcf,
    peer_comparison,
    score_altman_z,
    score_piotroski_f,
)
from quantagent.tools.market_breadth import (
    compute_advance_decline,
    compute_breadth_thrust,
    compute_market_sentiment,
    compute_new_highs_lows,
    compute_percent_above_ma,
    count_distribution_days,
    detect_follow_through_day,
    detect_market_regime,
)
from quantagent.tools.market_data import (
    get_earnings_calendar,
    get_economic_indicators,
    get_fundamentals,
    get_news,
    get_ohlcv,
    get_quote,
    get_sector_performance,
    search_symbols,
)
from quantagent.tools.market_overview import (
    generate_market_heatmap,
    get_market_summary,
    get_most_active,
    get_top_movers,
)
from quantagent.tools.pair_trading import (
    compute_spread_metrics,
    find_cointegrated_pairs,
)
from quantagent.tools.portfolio import (
    compute_portfolio_metrics,
    monte_carlo_simulation,
    optimize_portfolio,
)
from quantagent.tools.providers import get_active_provider
from quantagent.tools.reports import (
    Report,
    export_report_html,
    export_report_markdown,
    generate_market_daily,
    generate_portfolio_report,
    generate_screening_report,
    generate_sector_report,
    generate_stock_report,
    render_markdown,
)
from quantagent.tools.risk_gate import check_circuit_breaker, check_discipline_gate
from quantagent.tools.screener import (
    screen_breakout_candidates,
    screen_by_technicals,
    screen_combined,
    screen_oversold_reversal,
    screen_stocks,
    screen_vcp_pattern,
)
from quantagent.tools.sector_analysis import (
    compute_sector_relative_strength,
    detect_sector_rotation,
    get_industry_performance,
    get_sector_performance_ranked,
)
from quantagent.tools.technical import (
    compute_indicators,
    detect_patterns,
    detect_support_resistance,
)
from quantagent.tools.trade_journal import (
    close_trade,
    compute_trade_stats,
    get_open_trades,
    get_trade_history,
    log_trade_idea,
    update_trade_status,
)
from quantagent.tools.universe import (
    create_universe,
    delete_universe,
    get_universe_metadata,
    list_universes,
)
from quantagent.tools.workflows import get_workflow, list_workflows, run_workflow
from quantagent.tui.config import QuantAgentConfig

logger = logging.getLogger(__name__)

_TOOL_TIMEOUT_SEC = 30
# Universe-scale operations (screening, breadth) may fetch data for hundreds
# of symbols on a cold cache and need more headroom than the default.
_LONG_TOOL_TIMEOUT_SEC = 120
# Explicit whole-universe cache warm-up is allowed to run for minutes.
_WARMUP_TIMEOUT_SEC = 600

# ── Helpers ──────────────────────────────────────────────────────────────────


def _parse_comma_symbols(symbols: str) -> list[str]:
    """Split comma-separated symbols, strip whitespace, uppercase."""
    return [s.strip().upper() for s in symbols.split(",")]


def _parse_comma_weights(weights: str) -> list[float]:
    """Split comma-separated weight strings into floats."""
    return [float(x) for x in weights.split(",")]


def _parse_symbols_and_weights(symbols: str, weights: str) -> dict[str, float]:
    """Parse comma-separated symbols/weights and zip them into a dict.

    Args:
        symbols: Comma-separated list of stock symbols.
        weights: Comma-separated list of weights, one per symbol.

    Returns:
        Mapping of symbol to weight, in input order.

    Raises:
        ValueError: If the parsed symbol and weight lists have different
            lengths (rather than silently truncating to the shorter list).
    """
    sym_list = _parse_comma_symbols(symbols)
    w_list = _parse_comma_weights(weights)
    if len(sym_list) != len(w_list):
        raise ValueError(
            "symbols and weights must have the same number of comma-separated "
            f"entries: got {len(sym_list)} symbol(s) {sym_list} and "
            f"{len(w_list)} weight(s) {w_list}."
        )
    return dict(zip(sym_list, w_list, strict=True))


def _json_dumps(obj: Any) -> str:
    """Serialize to JSON with standard indent and str fallback."""
    return json.dumps(obj, indent=2, default=str)


async def _with_timeout(coro: Any, timeout: float = _TOOL_TIMEOUT_SEC) -> Any:
    """Wrap an awaitable with a timeout, raising TimeoutError on expiry."""
    async with asyncio.timeout(timeout):
        return await coro


def _bind_provider(func: Any, provider: Any) -> Any:
    """Wrap a ``(provider, ...)`` function into a @tool with provider injected.

    Sets ``__signature__`` on the wrapper so langchain infer_schema sees the
    real tool parameters instead of ``*args, **kwargs``.
    """
    sig = inspect.signature(func)
    tool_params = {
        n: p for n, p in sig.parameters.items() if n != "provider"
    }
    new_sig = sig.replace(parameters=list(tool_params.values()))
    name = func.__name__.removeprefix("_")

    async def _wrapped(*args: Any, **kwargs: Any) -> str:
        return await func(provider, *args, **kwargs)  # type: ignore[no-any-return]

    _wrapped.__name__ = name
    _wrapped.__doc__ = func.__doc__
    _wrapped.__signature__ = new_sig  # type: ignore[attr-defined]
    _wrapped.__annotations__ = {
        n: p.annotation for n, p in tool_params.items()
    }
    return tool(_wrapped)


# ── Provider-independent tools (decorated at module level) ───────────────────
# Error handling is delegated to ErrorLoggingMiddleware which wraps every
# tool call via wrap_tool_call — logs full tracebacks then returns error
# strings to the LLM.


@tool
async def compute_dcf_valuation(
    free_cash_flows: str,
    growth_rate: float,
    discount_rate: float,
    terminal_growth: float,
    shares_outstanding: float,
) -> str:
    """Compute discounted cash flow valuation.

    Args:
        free_cash_flows: Comma-separated list of projected FCFs.
        growth_rate: Growth rate for projection period (decimal, e.g. 0.05).
        discount_rate: WACC / discount rate (decimal, e.g. 0.10).
        terminal_growth: Perpetual growth rate (decimal, e.g. 0.02).
        shares_outstanding: Shares outstanding in millions.
    """
    fcf_list = [float(x) for x in free_cash_flows.split(",")]
    result = compute_dcf(
        fcf_list, growth_rate, discount_rate, terminal_growth, shares_outstanding,
    )
    return _json_dumps(result)


@tool
async def compute_piotroski_score(fundamentals_json: str) -> str:
    """Compute Piotroski F-Score from fundamental data.

    Args:
        fundamentals_json: JSON string of fundamental data fields.
    """
    data = json.loads(fundamentals_json)
    result = score_piotroski_f(data)
    return _json_dumps(result)


@tool
async def compute_altman_z(fundamentals_json: str) -> str:
    """Compute Altman Z-Score from fundamental data.

    Args:
        fundamentals_json: JSON string of fundamental data fields.
    """
    data = json.loads(fundamentals_json)
    result = score_altman_z(data)
    return _json_dumps(result)


@tool
async def journal_log_trade(
    symbol: str,
    thesis: str,
    entry_plan: str,
    target: float | None = None,
    stop: float | None = None,
) -> str:
    """Log a new trade idea in the trade journal (status: idea).

    Args:
        symbol: Stock ticker symbol.
        thesis: Why this trade — the falsifiable reasoning.
        entry_plan: Entry conditions, planned size, and timeframe.
        target: Price target (optional).
        stop: Stop-loss price — strongly recommended; the discipline
            gate blocks entries without one.
    """
    trade = await log_trade_idea(symbol, thesis, entry_plan, target=target, stop=stop)
    return trade.model_dump_json(indent=2)


@tool
async def journal_update_status(
    trade_id: str,
    status: str,
    notes: str = "",
    entry_price: float | None = None,
) -> str:
    """Advance a journaled trade's status (forward-only lifecycle).

    Lifecycle: idea -> entry_ready -> active -> partially_closed ->
    closed; idea/entry_ready may also move to invalidated. Backward
    transitions are rejected.

    Args:
        trade_id: Journal trade id.
        status: New status.
        notes: Optional note appended to the trade.
        entry_price: Required when moving to active.
    """
    trade = await update_trade_status(
        trade_id, status, notes=notes or None, entry_price=entry_price
    )
    return trade.model_dump_json(indent=2)


@tool
async def journal_open_trades() -> str:
    """List all open trade ideas in the journal (not closed/invalidated)."""
    trades = await get_open_trades()
    if not trades:
        return "The trade journal has no open trades."
    return _json_dumps([t.model_dump(mode="json") for t in trades])


@tool
async def journal_history(days: int = 30, status: str = "") -> str:
    """Fetch journal trade history.

    Args:
        days: Lookback window in days (default 30).
        status: Optional status filter (idea, entry_ready, active,
            partially_closed, closed, invalidated).
    """
    trades = await get_trade_history(days=days, status=status or None)
    if not trades:
        return "No journaled trades in that window."
    return _json_dumps([t.model_dump(mode="json") for t in trades])


@tool
async def journal_stats() -> str:
    """Compute trade journal statistics.

    Returns win rate, average win/loss, profit factor, expectancy,
    max consecutive losses, and average MAE/MFE over closed trades.
    """
    return _json_dumps(await compute_trade_stats())


@tool
async def check_risk_circuit_breaker() -> str:
    """Check the drawdown circuit breaker before planning new trades.

    Evaluates journal P&L against daily (2%), weekly (5%), and monthly
    (8%) loss limits plus a losing-streak cooldown. Returns
    trading_allowed, cooldown, or halted with the triggered rules.
    This is a recommendation gate — it never touches a broker.
    """
    return _json_dumps(await check_circuit_breaker())


# ── Provider-dependent tool implementations (bare, bound at runtime) ─────────
# Error handling is delegated to ErrorLoggingMiddleware (wrap_tool_call).


async def _get_stock_quote(provider: Any, symbol: str) -> str:
    """Fetch the current stock quote for a symbol.

    Args:
        symbol: Stock ticker symbol (e.g. AAPL, MSFT).
    """
    result = await _with_timeout(get_quote(provider, symbol))
    return _json_dumps(result)


async def _get_ohlcv_data(
    provider: Any, symbol: str, period: str = "1y", interval: str = "1d",
) -> str:
    """Fetch OHLCV price history for a symbol.

    Args:
        symbol: Stock ticker symbol.
        period: Time period — 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y.
        interval: Bar interval — 1m, 5m, 15m, 30m, 60m, 1d, 1wk, 1mo.
    """
    df = await _with_timeout(get_ohlcv(provider, symbol, period=period, interval=interval))
    summary = {
        "symbol": symbol,
        "period": period,
        "interval": interval,
        "bars": len(df),
        "latest_close": round(float(df["Close"].iloc[-1]), 4),
        "latest_volume": int(df["Volume"].iloc[-1]),
        "date_range": [df.index[0].isoformat(), df.index[-1].isoformat()],
    }
    return _json_dumps(summary)


async def _get_stock_fundamentals(provider: Any, symbol: str) -> str:
    """Fetch fundamental data for a symbol.

    Args:
        symbol: Stock ticker symbol.
    """
    result = await _with_timeout(get_fundamentals(provider, symbol))
    return _json_dumps(result)


async def _get_stock_news(provider: Any, symbol: str, days: int = 7) -> str:
    """Fetch recent news headlines for a symbol.

    Args:
        symbol: Stock ticker symbol.
        days: Number of days to look back.
    """
    result = await _with_timeout(get_news(provider, symbol, days=days))
    return _json_dumps(result)


async def _search_stock_symbols(provider: Any, query: str) -> str:
    """Search for stock symbols by company name.

    Args:
        query: Company name or partial ticker to search for.
    """
    result = await _with_timeout(search_symbols(provider, query))
    return _json_dumps(result)


async def _compute_technical_indicators(provider: Any, symbol: str, indicators: str) -> str:
    """Compute technical indicators for a symbol.

    Args:
        symbol: Stock ticker symbol.
        indicators: Comma-separated list of indicators such as
            sma_20, ema_50, rsi_14, macd, bbands, atr_14, adx_14, obv,
            stoch_k, stoch_d, vwap, supertrend.
    """
    df = await _with_timeout(get_ohlcv(provider, symbol, period="1y"))
    indicator_list = [i.strip() for i in indicators.split(",")]
    result_df = compute_indicators(df, indicator_list)
    cols = [c for c in result_df.columns if c not in {"Open", "High", "Low", "Close", "Volume"}]
    latest = result_df.iloc[-1][["Close"] + cols]
    return _json_dumps({"symbol": symbol, "latest": latest.round(4).to_dict()})


async def _detect_chart_patterns(provider: Any, symbol: str) -> str:
    """Detect candlestick patterns for a symbol.

    Args:
        symbol: Stock ticker symbol.
    """
    df = await _with_timeout(get_ohlcv(provider, symbol, period="3mo"))
    patterns = detect_patterns(df)
    return _json_dumps({"symbol": symbol, "patterns": patterns[:10]})


async def _get_support_resistance(provider: Any, symbol: str) -> str:
    """Detect support and resistance levels for a symbol.

    Args:
        symbol: Stock ticker symbol.
    """
    df = await _with_timeout(get_ohlcv(provider, symbol, period="6mo"))
    levels = detect_support_resistance(df)
    return _json_dumps(levels)


async def _run_backtest_tool(
    provider: Any, symbol: str, strategy: str, period: str = "5y",
) -> str:
    """Run a backtest for a symbol using a trading strategy.

    Args:
        symbol: Stock ticker symbol.
        strategy: Strategy name — sma_crossover, ema_crossover,
            rsi_mean_reversion, macd_momentum, bollinger_breakout, buy_and_hold.
        period: Backtest period — 1y, 2y, 5y, 10y.
    """
    config = BacktestConfig(symbol=symbol.upper(), strategy=strategy, period=period)
    result = await _with_timeout(run_backtest(provider, config))
    return format_backtest_result(result)


async def _screen_stocks_tool(
    provider: Any,
    universe: str = "sp500",
    criteria: str = "",
    sort_by: str = "market_cap",
    limit: int = 20,
) -> str:
    """Screen stocks by fundamental criteria.

    Args:
        universe: Universe to screen — sp500, nasdaq100.
        criteria: JSON string of criteria, e.g. '{"pe_lt": 15, "roe_gt": 0.20}'.
            Supported keys: pe_lt/gt, pb_lt, roe_gt, roa_gt, debt_equity_lt,
            mcap_gt/lt, volume_gt, dividend_yield_gt, revenue_growth_gt,
            eps_growth_gt, beta_lt.
        sort_by: Field to sort by.
        limit: Maximum results to return.
    """
    crit = json.loads(criteria) if criteria else {}
    df = await _with_timeout(screen_stocks(
        provider, universe=universe, criteria=crit, sort_by=sort_by, limit=limit,
    ), timeout=_LONG_TOOL_TIMEOUT_SEC)
    if df.empty:
        return "No stocks matched the criteria."
    return str(df.to_json(orient="records", indent=2))


async def _optimize_portfolio_tool(
    provider: Any, symbols: str, method: str = "max_sharpe",
) -> str:
    """Optimize portfolio weights for a list of symbols.

    Args:
        symbols: Comma-separated list of stock symbols.
        method: Optimization method — max_sharpe, min_vol, risk_parity, equal_weight.
    """
    sym_list = _parse_comma_symbols(symbols)
    result = await _with_timeout(optimize_portfolio(provider, sym_list, method=method))
    return _json_dumps(result)


async def _compute_portfolio_risk(provider: Any, symbols: str, weights: str) -> str:
    """Compute portfolio risk metrics.

    Args:
        symbols: Comma-separated list of stock symbols.
        weights: Comma-separated list of weights (must sum to ~1.0).
    """
    weight_dict = _parse_symbols_and_weights(symbols, weights)
    result = await _with_timeout(compute_portfolio_metrics(provider, weight_dict))
    return _json_dumps(result)


async def _run_monte_carlo(provider: Any, symbols: str, weights: str) -> str:
    """Run Monte Carlo simulation for a portfolio.

    Args:
        symbols: Comma-separated list of stock symbols.
        weights: Comma-separated list of weights.
    """
    weight_dict = _parse_symbols_and_weights(symbols, weights)
    result = await _with_timeout(monte_carlo_simulation(provider, weight_dict))
    return _json_dumps(result)


async def _compare_peers(provider: Any, symbols: str) -> str:
    """Compare fundamentals across multiple peers.

    Args:
        symbols: Comma-separated list of stock symbols.
    """
    sym_list = _parse_comma_symbols(symbols)
    fund_map = {}
    for sym in sym_list:
        fund_map[sym] = await _with_timeout(get_fundamentals(provider, sym))
    df = peer_comparison(fund_map)
    return df.to_json(orient="index", indent=2)


async def _get_earnings_calendar(
    provider: Any, symbol: str, lookahead_days: int = 90
) -> str:
    """Fetch upcoming earnings dates for a symbol.

    Args:
        symbol: Stock ticker symbol.
        lookahead_days: Days ahead to search (default 90).
    """
    result = await _with_timeout(get_earnings_calendar(provider, symbol, lookahead_days=lookahead_days))
    return _json_dumps(result)


async def _get_sector_performance(provider: Any) -> str:
    """Fetch performance across all major market sectors.

    Returns 1D, 1W, 1M, 3M, and YTD returns for each sector.
    """
    result = await _with_timeout(get_sector_performance(provider))
    return _json_dumps(result)


async def _get_economic_indicators(provider: Any) -> str:
    """Fetch macroeconomic indicators.

    Returns VIX, treasury yields (2Y, 10Y), S&P 500 PE, GDP growth,
    CPI, and unemployment rate. Fields unavailable from the provider
    are returned as null.
    """
    result = await _with_timeout(get_economic_indicators(provider))
    return _json_dumps(result)


async def _get_sector_performance_ranked(provider: Any, periods: str = "") -> str:
    """Rank all 11 GICS sectors by performance across multiple timeframes.

    Args:
        periods: Comma-separated timeframes from 1d, 1w, 1m, 3m, 6m, 1y.
            Empty uses all six.
    """
    period_list = [p.strip() for p in periods.split(",")] if periods else None
    df = await _with_timeout(get_sector_performance_ranked(provider, periods=period_list))
    return str(df.to_json(orient="records", indent=2))


async def _get_industry_performance(provider: Any, sector: str) -> str:
    """Rank industries within a sector by 1m/3m performance.

    Classifies S&P 500 members into industries (cached weekly). Slow on
    first use for a universe — up to two minutes on the free tier.

    Args:
        sector: Sector name, e.g. Technology, Healthcare, Financials.
    """
    df = await _with_timeout(
        get_industry_performance(provider, sector), timeout=_LONG_TOOL_TIMEOUT_SEC
    )
    if df.empty:
        return f"No industry data found for sector: {sector}"
    return str(df.to_json(orient="records", indent=2))


async def _compute_sector_relative_strength(
    provider: Any, benchmark: str = "SPY", period: str = "3m"
) -> str:
    """Compute each sector's relative strength vs a benchmark.

    Args:
        benchmark: Benchmark symbol (default SPY).
        period: RS window — 1w, 1m, 3m, 6m, 1y.
    """
    df = await _with_timeout(
        compute_sector_relative_strength(provider, benchmark=benchmark, period=period)
    )
    return str(df.to_json(orient="records", indent=2))


async def _detect_sector_rotation(provider: Any, lookback_days: int = 90) -> str:
    """Detect sector rotation: leading/lagging/improving/deteriorating sectors.

    Also returns a risk-on/risk-off rotation signal and an estimated
    economic cycle phase.

    Args:
        lookback_days: Relative-strength lookback in sessions (default 90).
    """
    result = await _with_timeout(detect_sector_rotation(provider, lookback_days=lookback_days))
    return _json_dumps(result)


async def _count_distribution_days(provider: Any, index_symbol: str = "SPY") -> str:
    """Count IBD-style distribution days (institutional selling) on an index.

    Five or more in 25 sessions signals a market under pressure.

    Args:
        index_symbol: Index ETF to analyze — SPY or QQQ.
    """
    result = await _with_timeout(count_distribution_days(provider, index_symbol=index_symbol))
    return _json_dumps(result)


async def _detect_follow_through_day(provider: Any, index_symbol: str = "SPY") -> str:
    """Detect an O'Neil Follow-Through Day confirming a new uptrend.

    Returns correction/rally-attempt/confirmed-uptrend status.

    Args:
        index_symbol: Index ETF to analyze — SPY or QQQ.
    """
    result = await _with_timeout(detect_follow_through_day(provider, index_symbol=index_symbol))
    return _json_dumps(result)


async def _detect_market_regime(provider: Any) -> str:
    """Detect the current market regime with a recommended exposure band.

    Combines cross-asset ratios (RSP/SPY, IWM/SPY, XLY/XLP, SPY/TLT,
    HYG/LQD), index trend, VIX, and sector breadth into a 0-100 score
    mapped to strong-bull/bull/neutral/bear/strong-bear plus a suggested
    equity exposure range.
    """
    result = await _with_timeout(detect_market_regime(provider))
    return _json_dumps(result)


async def _get_market_summary(provider: Any) -> str:
    """One-shot market overview: indices, timing signals, breadth, regime.

    Includes distribution-day count, follow-through-day status, percent
    of sectors above key moving averages, market regime with recommended
    exposure, and SPY support/resistance levels.
    """
    result = await _with_timeout(get_market_summary(provider), timeout=_LONG_TOOL_TIMEOUT_SEC)
    return _json_dumps(result)


def _df_or_message(df: Any, empty_message: str) -> str:
    if df.empty:
        return empty_message
    return str(df.to_json(orient="records", indent=2))


async def _screen_technicals_tool(
    provider: Any, criteria: str, universe: str = "sp500", limit: int = 20
) -> str:
    """Screen stocks by technical criteria computed from daily OHLCV.

    Args:
        criteria: JSON string, e.g. '{"rsi_lt": 30, "price_above_sma": 200}'.
            Supported keys: rsi_lt/rsi_gt (float), macd_bullish (bool),
            price_above_sma/price_below_sma (SMA period), volume_expansion
            (min ratio vs 20d avg), atr_breakout (bool), adx_gt (float).
        universe: Universe to screen — sp500, nasdaq100, sector_etfs, or custom.
        limit: Maximum results.
    """
    crit = json.loads(criteria)
    df = await _with_timeout(
        screen_by_technicals(provider, crit, universe=universe, limit=limit),
        timeout=_LONG_TOOL_TIMEOUT_SEC,
    )
    return _df_or_message(df, "No stocks matched the technical criteria.")


async def _screen_combined_tool(
    provider: Any,
    technical_criteria: str = "",
    fundamental_criteria: str = "",
    universe: str = "sp500",
    limit: int = 20,
) -> str:
    """Screen by combined fundamental + technical criteria (intersection).

    Fundamental filters run first (cheap), technicals only on survivors.

    Args:
        technical_criteria: JSON string (see screen_technicals_tool keys).
        fundamental_criteria: JSON string (see screen_stocks_tool keys).
        universe: Universe to screen.
        limit: Maximum results.
    """
    tech = json.loads(technical_criteria) if technical_criteria else None
    fund = json.loads(fundamental_criteria) if fundamental_criteria else None
    df = await _with_timeout(
        screen_combined(provider, technical_criteria=tech,
                        fundamental_criteria=fund, universe=universe, limit=limit),
        timeout=_LONG_TOOL_TIMEOUT_SEC,
    )
    return _df_or_message(df, "No stocks matched the combined criteria.")


async def _screen_vcp_tool(
    provider: Any, universe: str = "sp500", limit: int = 20
) -> str:
    """Screen for Minervini Volatility Contraction Patterns (VCP).

    Finds stocks with a prior 30%+ advance now forming a tightening,
    low-volume consolidation above the 200-day SMA — classic pre-breakout
    structure.

    Args:
        universe: Universe to screen.
        limit: Maximum results.
    """
    df = await _with_timeout(
        screen_vcp_pattern(provider, universe=universe, limit=limit),
        timeout=_LONG_TOOL_TIMEOUT_SEC,
    )
    return _df_or_message(df, "No VCP candidates found.")


async def _screen_breakouts_tool(
    provider: Any,
    universe: str = "sp500",
    proximity_to_high_pct: float = 0.05,
    volume_ratio_min: float = 1.5,
    limit: int = 20,
) -> str:
    """Screen for stocks near 52-week highs with volume expansion.

    Args:
        universe: Universe to screen.
        proximity_to_high_pct: Max distance below the 52-week high (0.05 = 5%).
        volume_ratio_min: Minimum last-day volume vs 20-day average.
        limit: Maximum results.
    """
    df = await _with_timeout(
        screen_breakout_candidates(
            provider, universe=universe,
            proximity_to_high_pct=proximity_to_high_pct,
            volume_ratio_min=volume_ratio_min, limit=limit,
        ),
        timeout=_LONG_TOOL_TIMEOUT_SEC,
    )
    return _df_or_message(df, "No breakout candidates found.")


async def _screen_oversold_tool(
    provider: Any,
    universe: str = "sp500",
    rsi_threshold: float = 30.0,
    min_decline_pct: float = 0.20,
    limit: int = 20,
) -> str:
    """Screen for oversold reversal candidates.

    RSI below the threshold, price down sharply from its 6-month high,
    and showing a reversal bar (up day closing in the upper half of its
    range).

    Args:
        universe: Universe to screen.
        rsi_threshold: Maximum RSI-14 (default 30).
        min_decline_pct: Minimum decline from the 6-month high (0.20 = 20%).
        limit: Maximum results.
    """
    df = await _with_timeout(
        screen_oversold_reversal(
            provider, universe=universe, rsi_threshold=rsi_threshold,
            min_decline_pct=min_decline_pct, limit=limit,
        ),
        timeout=_LONG_TOOL_TIMEOUT_SEC,
    )
    return _df_or_message(df, "No oversold reversal candidates found.")


async def _list_universes_tool(provider: Any) -> str:
    """List all available screening universes (built-in and custom)."""
    names = list_universes()
    return _json_dumps([get_universe_metadata(n) for n in names])


async def _create_universe_tool(provider: Any, name: str, symbols: str) -> str:
    """Create or update a custom screening universe.

    Args:
        name: Universe name (lowercase letters, digits, _ or -).
        symbols: Comma-separated ticker symbols.
    """
    create_universe(name, _parse_comma_symbols(symbols))
    return _json_dumps(get_universe_metadata(name))


async def _delete_universe_tool(provider: Any, name: str) -> str:
    """Delete a custom screening universe.

    Args:
        name: Custom universe name (built-ins cannot be deleted).
    """
    delete_universe(name)
    return f"Universe '{name}' deleted."


async def _journal_close_trade(
    provider: Any, trade_id: str, exit_price: float, outcome_notes: str = ""
) -> str:
    """Close an active journaled trade, recording P&L and MAE/MFE.

    Computes realized P&L vs the entry price and the maximum
    adverse/favorable excursion over the holding period from OHLCV.

    Args:
        trade_id: Journal trade id (must be active or partially_closed).
        exit_price: Exit fill price.
        outcome_notes: Postmortem note (what worked / what didn't).
    """
    trade = await _with_timeout(
        close_trade(provider, trade_id, exit_price, outcome_notes=outcome_notes or None)
    )
    return str(trade.model_dump_json(indent=2))


async def _check_trade_discipline(provider: Any, trade_id: str) -> str:
    """Run the pre-trade discipline gate on a journaled trade idea.

    Blocks (result: blocked) when the thesis/entry plan is missing, no
    stop is defined, the circuit breaker is tripped, or the market
    regime is reduce-only (bear/strong-bear). Run this before moving
    any trade to entry_ready or active.

    Args:
        trade_id: Journal trade id to validate.
    """
    result = await _with_timeout(
        check_discipline_gate(provider, trade_id), timeout=_LONG_TOOL_TIMEOUT_SEC
    )
    return _json_dumps(result)


async def _find_cointegrated_pairs(
    provider: Any,
    universe: str = "sp500",
    sector: str = "",
    max_symbols: int = 60,
    limit: int = 20,
) -> str:
    """Find cointegrated stock pairs for statistical arbitrage.

    Scans pairs within a universe (Engle-Granger test, correlation
    pre-filter). Restricting to one sector is strongly recommended —
    cross-sector pairs cointegrate by accident more often than by
    economics. Returns hedge ratio, half-life, and current z-score
    per pair.

    Args:
        universe: Universe to scan — sp500, nasdaq100, sector_etfs, or custom.
        sector: Optional sector filter (e.g. Energy, Technology).
        max_symbols: Cap on symbols scanned (pair count grows quadratically).
        limit: Maximum pairs returned.
    """
    df = await _with_timeout(
        find_cointegrated_pairs(
            provider, universe=universe, sector=sector or None,
            max_symbols=max_symbols, limit=limit,
        ),
        timeout=_LONG_TOOL_TIMEOUT_SEC,
    )
    return _df_or_message(df, "No cointegrated pairs found.")


async def _compute_spread_metrics(
    provider: Any, symbol_a: str, symbol_b: str, period: str = "1y"
) -> str:
    """Compute pair-trading spread metrics for two symbols.

    Returns the OLS hedge ratio, cointegration p-value, current spread
    z-score, mean-reversion half-life in days, and an entry/exit signal
    (|z| >= 2 entry-zone with legs stated, |z| <= 0.5 exit-zone).

    Args:
        symbol_a: First leg (spread = a - hedge_ratio * b).
        symbol_b: Second leg.
        period: History window — 6mo, 1y, 2y.
    """
    result = await _with_timeout(
        compute_spread_metrics(provider, symbol_a, symbol_b, period=period)
    )
    return _json_dumps(result)


async def _analyze_earnings_impact(provider: Any, symbol: str, quarters: int = 8) -> str:
    """Analyze how a stock historically reacts to its earnings reports.

    Per past report: overnight gap, day-1 move, and 5d/20d post-event
    drift, plus aggregates (average absolute move, positive rate).
    Useful for sizing expectations ahead of an upcoming report.

    Args:
        symbol: Stock ticker symbol.
        quarters: Number of past reports to analyze (default 8).
    """
    result = await _with_timeout(
        analyze_earnings_impact(provider, symbol, quarters=quarters)
    )
    return _json_dumps(result)


async def _get_earnings_calendar_range(
    provider: Any,
    start_date: str,
    end_date: str,
    universe: str = "sp500",
    symbols: str = "",
) -> str:
    """Upcoming earnings for a universe within a date range.

    Slow on first use for a full universe (per-symbol fetches, cached
    12h); pass explicit symbols for a fast targeted lookup.

    Args:
        start_date: Range start (YYYY-MM-DD).
        end_date: Range end (YYYY-MM-DD).
        universe: Universe to scan when symbols is empty.
        symbols: Optional comma-separated symbols.
    """
    symbol_list = _parse_comma_symbols(symbols) if symbols else None
    df = await _with_timeout(
        get_earnings_calendar_range(
            provider, start_date, end_date, universe=universe, symbols=symbol_list
        ),
        timeout=_WARMUP_TIMEOUT_SEC,
    )
    return _df_or_message(df, "No earnings reports in that range.")


async def _synthesize_conviction_tool(provider: Any) -> str:
    """Synthesize a 0-100 market conviction score with exposure guidance.

    Fuses market regime, breadth, timing signals (distribution days,
    follow-through day), sector rotation, and sentiment, with a bonus
    for signal convergence. Returns the score, a stance
    (aggressive/constructive/selective/defensive/risk-off), a
    recommended equity exposure band, per-component breakdown, and key
    risks. Use this to answer "how bullish should I be right now?".
    """
    result = await _with_timeout(
        synthesize_conviction(provider), timeout=_LONG_TOOL_TIMEOUT_SEC
    )
    return _json_dumps(result)


def _serialize_step_value(value: Any) -> Any:
    if hasattr(value, "to_dict") and hasattr(value, "columns"):  # DataFrame
        return json.loads(value.head(10).to_json(orient="records"))
    return value


async def _list_workflows_tool(provider: Any) -> str:
    """List available analysis workflows (built-in and custom)."""
    return _json_dumps(list_workflows())


async def _run_workflow_tool(provider: Any, name: str, target: str = "") -> str:
    """Run a predefined analysis workflow and return all step results.

    Built-in workflows: daily_market_check, weekly_sector_review,
    stock_research (target = symbol), screening_pipeline,
    portfolio_rebalance_review (target = comma-separated symbols).
    Custom workflows come from ~/.quantagent/workflows/<name>.yaml.

    Args:
        name: Workflow name (see list_workflows_tool).
        target: Required for stock_research and portfolio_rebalance_review.
    """
    workflow = get_workflow(name, target=target)
    result = await _with_timeout(
        run_workflow(provider, workflow), timeout=_WARMUP_TIMEOUT_SEC
    )
    payload = {
        "workflow": result.workflow_name,
        "summary": result.summary,
        "results": {
            key: _serialize_step_value(value)
            for key, value in result.step_results.items()
        },
    }
    text = _json_dumps(payload)
    if len(text) > 12_000:
        text = text[:12_000] + "\n... [truncated]"
    return text


async def _build_report(
    provider: Any, report_type: str, target: str, criteria: str, universe: str
) -> Report:
    if report_type == "market":
        return await generate_market_daily(provider)
    if report_type == "sector":
        return await generate_sector_report(provider, target)
    if report_type == "stock":
        return await generate_stock_report(provider, target)
    if report_type == "portfolio":
        return await generate_portfolio_report(provider, _parse_comma_symbols(target))
    if report_type == "screening":
        crit = json.loads(criteria) if criteria else None
        return await generate_screening_report(
            provider, screen_type=target or "fundamental",
            criteria=crit, universe=universe,
        )
    raise ValueError(
        f"Unknown report type: {report_type}. "
        "Valid: market, sector, stock, portfolio, screening."
    )


async def _generate_report_tool(
    provider: Any,
    report_type: str,
    target: str = "",
    fmt: str = "markdown",
    universe: str = "sp500",
    criteria: str = "",
) -> str:
    """Generate a structured report and save it to ~/.quantagent/reports/.

    Args:
        report_type: market | sector | stock | portfolio | screening.
        target: Depends on type — sector name (sector), ticker (stock),
            comma-separated tickers (portfolio), or screen type
            fundamental/technical/vcp/breakout/oversold (screening).
            Unused for market.
        fmt: Output format — markdown or html.
        universe: Universe for screening reports.
        criteria: JSON criteria string for screening reports.
    """
    report = await _with_timeout(
        _build_report(provider, report_type, target, criteria, universe),
        timeout=_LONG_TOOL_TIMEOUT_SEC,
    )
    slug = f"{report_type}{'-' + target.replace(',', '_').lower() if target else ''}"
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    ext = "html" if fmt == "html" else "md"
    path = reports_dir() / f"{slug}-{stamp}.{ext}"
    if fmt == "html":
        export_report_html(report, path)
    else:
        export_report_markdown(report, path)
    rendered = render_markdown(report)
    preview = rendered[:4000] + ("\n\n_[truncated]_" if len(rendered) > 4000 else "")
    return f"Report saved to {path}\n\n{preview}"


async def _warm_breadth_cache(provider: Any, universe: str = "sp500") -> str:
    """Warm the universe breadth cache (one-time, slow — up to 10 minutes).

    Downloads ~1 year of daily data for every universe member into the
    local breadth store. Run this once before universe-level breadth
    tools (advance/decline, new highs/lows, breadth thrust, top movers);
    afterwards they update incrementally and respond in seconds.

    Args:
        universe: Universe to warm — sp500, nasdaq100, sector_etfs.
    """
    store = BreadthStore()
    result = await _with_timeout(
        store.warm_up(provider, universe), timeout=_WARMUP_TIMEOUT_SEC
    )
    return _json_dumps(result)


def _history_payload(df: Any, tail: int = 10) -> str:
    """Serialize a breadth history frame as latest values + recent tail."""
    if df.empty:
        return _json_dumps({"error": "no data — warm the breadth cache first"})
    records = json.loads(df.tail(tail).to_json(orient="index", date_format="iso"))
    return _json_dumps({"latest": df.iloc[-1].to_dict(), "recent": records})


async def _compute_advance_decline(
    provider: Any, universe: str = "sp500", period: str = "3m"
) -> str:
    """Compute the advance/decline line for a universe.

    Requires a warm breadth cache (see warm_breadth_cache); warms it
    automatically on first use, which is slow.

    Args:
        universe: Universe name — sp500, nasdaq100, sector_etfs.
        period: History window — 1m, 3m, 6m, 1y.
    """
    df = await _with_timeout(
        compute_advance_decline(provider, universe=universe, period=period),
        timeout=_WARMUP_TIMEOUT_SEC,
    )
    return _history_payload(df)


async def _compute_new_highs_lows(
    provider: Any, universe: str = "sp500", period: str = "3m"
) -> str:
    """Count daily new 52-week highs and lows for a universe.

    Requires a warm breadth cache; warms it automatically on first use.

    Args:
        universe: Universe name — sp500, nasdaq100, sector_etfs.
        period: History window — 1m, 3m, 6m, 1y.
    """
    df = await _with_timeout(
        compute_new_highs_lows(provider, universe=universe, period=period),
        timeout=_WARMUP_TIMEOUT_SEC,
    )
    return _history_payload(df)


async def _compute_breadth_thrust(
    provider: Any, universe: str = "sp500", period: str = "3m"
) -> str:
    """Compute the McClellan-style breadth oscillator for a universe.

    Above +50 = bullish thrust, below -50 = bearish. Requires a warm
    breadth cache; warms it automatically on first use.

    Args:
        universe: Universe name — sp500, nasdaq100, sector_etfs.
        period: History window — 1m, 3m, 6m, 1y.
    """
    result = await _with_timeout(
        compute_breadth_thrust(provider, universe=universe, period=period),
        timeout=_WARMUP_TIMEOUT_SEC,
    )
    history = result.pop("history")
    recent = (
        json.loads(history.tail(10).to_json(orient="index", date_format="iso"))
        if not history.empty
        else {}
    )
    return _json_dumps({**result, "recent": recent})


async def _compute_percent_above_ma(provider: Any, universe: str = "sector_etfs") -> str:
    """Percent of universe members above their 20/50/200-day moving averages.

    sector_etfs answers instantly; sp500/nasdaq100 use the breadth cache
    and fall back to a sector-ETF proxy (flagged) when the cache is cold.

    Args:
        universe: Universe name — sector_etfs, sp500, nasdaq100.
    """
    result = await _with_timeout(
        compute_percent_above_ma(provider, universe=universe, allow_warmup=False)
    )
    return _json_dumps(result)


async def _compute_market_sentiment(provider: Any) -> str:
    """Composite market sentiment score from -100 (fear) to +100 (greed).

    Combines VIX level, VIX term structure, sector breadth, and index
    momentum. Put/call ratio is unavailable and reported as null.
    """
    result = await _with_timeout(compute_market_sentiment(provider))
    return _json_dumps(result)


async def _get_top_movers(
    provider: Any,
    universe: str = "sp500",
    direction: str = "up",
    count: int = 10,
    period: str = "1d",
) -> str:
    """Top gainers or losers in a universe.

    Requires a warm breadth cache; warms it automatically on first use.

    Args:
        universe: Universe name — sp500, nasdaq100, sector_etfs.
        direction: "up" for gainers, "down" for losers.
        count: Number of symbols to return.
        period: Change window — 1d, 1w, 1m.
    """
    df = await _with_timeout(
        get_top_movers(provider, universe=universe, direction=direction,
                       count=count, period=period),
        timeout=_WARMUP_TIMEOUT_SEC,
    )
    if df.empty:
        return "No mover data available."
    return str(df.to_json(orient="records", indent=2))


async def _get_most_active(
    provider: Any, universe: str = "sp500", count: int = 10
) -> str:
    """Most active stocks by volume vs their 20-day average.

    Requires a warm breadth cache; warms it automatically on first use.

    Args:
        universe: Universe name — sp500, nasdaq100, sector_etfs.
        count: Number of symbols to return.
    """
    df = await _with_timeout(
        get_most_active(provider, universe=universe, count=count),
        timeout=_WARMUP_TIMEOUT_SEC,
    )
    if df.empty:
        return "No volume data available."
    return str(df.to_json(orient="records", indent=2))


async def _generate_market_heatmap(
    provider: Any,
    universe: str = "sp500",
    metric: str = "performance",
    group_by: str = "sector",
) -> str:
    """Market heatmap grouped by sector, summarized per group.

    Requires a warm breadth cache and symbol classifications (both
    cached). Returns per-group mean metric, symbol count, and the
    largest members by dollar volume.

    Args:
        universe: Universe name — sp500, nasdaq100.
        metric: performance | volume | volatility | rsi.
        group_by: "sector" or "industry".
    """
    result = await _with_timeout(
        generate_market_heatmap(provider, universe=universe, metric=metric,
                                group_by=group_by),
        timeout=_WARMUP_TIMEOUT_SEC,
    )
    return _json_dumps(_summarize_heatmap(result))


def _summarize_heatmap(result: dict) -> dict:
    """Reduce a full heatmap to per-group summaries digestible by the LLM."""
    summary = {}
    for group, members in result.get("groups", {}).items():
        cells = _flatten_cells(members)
        if not cells:
            continue
        values = [c["value"] for _, c in cells]
        largest = sorted(cells, key=lambda kv: kv[1]["size"] or 0, reverse=True)[:3]
        summary[group] = {
            "n_symbols": len(cells),
            "mean_value": round(sum(values) / len(values), 4),
            "largest": [{"symbol": s, "value": c["value"]} for s, c in largest],
        }
    return {"metric": result.get("metric"), "group_by": result.get("group_by"),
            "groups": summary}


def _flatten_cells(members: dict) -> list[tuple[str, dict]]:
    """Flatten one heatmap group ({sym: cell} or {industry: {sym: cell}})."""
    cells: list[tuple[str, dict]] = []
    for key, value in members.items():
        if isinstance(value, dict) and "value" in value:
            cells.append((key, value))
        elif isinstance(value, dict):
            cells.extend(_flatten_cells(value))
    return cells


# ── Registry builder ─────────────────────────────────────────────────────────


def build_tool_registry(config: QuantAgentConfig) -> list[Any]:
    """Build and return the list of LangChain tools."""
    provider = get_active_provider(config)
    return [
        _bind_provider(_get_stock_quote, provider),
        _bind_provider(_get_ohlcv_data, provider),
        _bind_provider(_get_stock_fundamentals, provider),
        _bind_provider(_get_stock_news, provider),
        _bind_provider(_search_stock_symbols, provider),
        _bind_provider(_compute_technical_indicators, provider),
        _bind_provider(_detect_chart_patterns, provider),
        _bind_provider(_get_support_resistance, provider),
        _bind_provider(_run_backtest_tool, provider),
        _bind_provider(_screen_stocks_tool, provider),
        _bind_provider(_optimize_portfolio_tool, provider),
        _bind_provider(_compute_portfolio_risk, provider),
        _bind_provider(_run_monte_carlo, provider),
        _bind_provider(_compare_peers, provider),
        _bind_provider(_get_earnings_calendar, provider),
        _bind_provider(_get_sector_performance, provider),
        _bind_provider(_get_economic_indicators, provider),
        _bind_provider(_get_sector_performance_ranked, provider),
        _bind_provider(_get_industry_performance, provider),
        _bind_provider(_compute_sector_relative_strength, provider),
        _bind_provider(_detect_sector_rotation, provider),
        _bind_provider(_count_distribution_days, provider),
        _bind_provider(_detect_follow_through_day, provider),
        _bind_provider(_detect_market_regime, provider),
        _bind_provider(_get_market_summary, provider),
        _bind_provider(_warm_breadth_cache, provider),
        _bind_provider(_compute_advance_decline, provider),
        _bind_provider(_compute_new_highs_lows, provider),
        _bind_provider(_compute_breadth_thrust, provider),
        _bind_provider(_compute_percent_above_ma, provider),
        _bind_provider(_compute_market_sentiment, provider),
        _bind_provider(_get_top_movers, provider),
        _bind_provider(_get_most_active, provider),
        _bind_provider(_generate_market_heatmap, provider),
        _bind_provider(_screen_technicals_tool, provider),
        _bind_provider(_screen_combined_tool, provider),
        _bind_provider(_screen_vcp_tool, provider),
        _bind_provider(_screen_breakouts_tool, provider),
        _bind_provider(_screen_oversold_tool, provider),
        _bind_provider(_list_universes_tool, provider),
        _bind_provider(_create_universe_tool, provider),
        _bind_provider(_delete_universe_tool, provider),
        _bind_provider(_generate_report_tool, provider),
        _bind_provider(_synthesize_conviction_tool, provider),
        _bind_provider(_list_workflows_tool, provider),
        _bind_provider(_run_workflow_tool, provider),
        _bind_provider(_journal_close_trade, provider),
        _bind_provider(_check_trade_discipline, provider),
        _bind_provider(_find_cointegrated_pairs, provider),
        _bind_provider(_compute_spread_metrics, provider),
        _bind_provider(_analyze_earnings_impact, provider),
        _bind_provider(_get_earnings_calendar_range, provider),
        journal_log_trade,
        journal_update_status,
        journal_open_trades,
        journal_history,
        journal_stats,
        check_risk_circuit_breaker,
        compute_dcf_valuation,
        compute_piotroski_score,
        compute_altman_z,
    ]

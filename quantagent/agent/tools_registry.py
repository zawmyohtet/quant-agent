"""LangChain @tool wrappers for all quant tools."""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
from typing import Any

from langchain.tools import tool

from quantagent.tools.backtesting import BacktestConfig, format_backtest_result, run_backtest
from quantagent.tools.fundamental import (
    compute_dcf,
    peer_comparison,
    score_altman_z,
    score_piotroski_f,
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
from quantagent.tools.portfolio import (
    compute_portfolio_metrics,
    monte_carlo_simulation,
    optimize_portfolio,
)
from quantagent.tools.providers import get_active_provider
from quantagent.tools.screener import screen_stocks
from quantagent.tools.technical import (
    compute_indicators,
    detect_patterns,
    detect_support_resistance,
)
from quantagent.tui.config import QuantAgentConfig

logger = logging.getLogger(__name__)

_TOOL_TIMEOUT_SEC = 30
# Universe-scale operations (screening, breadth) may fetch data for hundreds
# of symbols on a cold cache and need more headroom than the default.
_LONG_TOOL_TIMEOUT_SEC = 120

# ── Helpers ──────────────────────────────────────────────────────────────────


def _parse_comma_symbols(symbols: str) -> list[str]:
    """Split comma-separated symbols, strip whitespace, uppercase."""
    return [s.strip().upper() for s in symbols.split(",")]


def _parse_comma_weights(weights: str) -> list[float]:
    """Split comma-separated weight strings into floats."""
    return [float(x) for x in weights.split(",")]


def _json_dumps(obj: Any) -> str:
    """Serialize to JSON with standard indent and str fallback."""
    return json.dumps(obj, indent=2, default=str)


async def _with_timeout(coro: Any, timeout: float = _TOOL_TIMEOUT_SEC) -> Any:
    """Wrap an awaitable with a timeout, raising TimeoutError on expiry."""
    return await asyncio.wait_for(coro, timeout=timeout)


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
    sym_list = _parse_comma_symbols(symbols)
    w_list = _parse_comma_weights(weights)
    weight_dict = dict(zip(sym_list, w_list, strict=False))
    result = await _with_timeout(compute_portfolio_metrics(provider, weight_dict))
    return _json_dumps(result)


async def _run_monte_carlo(provider: Any, symbols: str, weights: str) -> str:
    """Run Monte Carlo simulation for a portfolio.

    Args:
        symbols: Comma-separated list of stock symbols.
        weights: Comma-separated list of weights.
    """
    sym_list = _parse_comma_symbols(symbols)
    w_list = _parse_comma_weights(weights)
    weight_dict = dict(zip(sym_list, w_list, strict=False))
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
        compute_dcf_valuation,
        compute_piotroski_score,
        compute_altman_z,
    ]

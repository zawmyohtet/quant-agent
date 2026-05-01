"""LangChain @tool wrappers for all quant tools."""
from __future__ import annotations

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
    get_fundamentals,
    get_news,
    get_ohlcv,
    get_quote,
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


def _tool_error(tool_name: str, detail: str) -> str:
    """Format a standard error message for tool failures."""
    return f"Error in {tool_name}: {detail}"


def _bind_provider(func: Any, provider: Any) -> Any:
    """Wrap a ``(provider, ...)`` function into a @tool with provider injected.

    The ``provider`` parameter is stripped from the LLM-visible schema so it
    is not exposed as a tool argument.
    """
    name = func.__name__.removeprefix("_")

    async def _wrapped(*args: Any, **kwargs: Any) -> str:
        return await func(provider, *args, **kwargs)  # type: ignore[no-any-return]

    _wrapped.__name__ = name
    _wrapped.__doc__ = func.__doc__
    _wrapped.__annotations__ = {
        k: v for k, v in func.__annotations__.items() if k != "provider"
    }
    return tool(_wrapped)


# ── Provider-independent tools (decorated at module level) ───────────────────


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
    try:
        fcf_list = [float(x) for x in free_cash_flows.split(",")]
        result = compute_dcf(
            fcf_list, growth_rate, discount_rate, terminal_growth, shares_outstanding,
        )
        return _json_dumps(result)
    except Exception as exc:
        return _tool_error("compute_dcf_valuation", str(exc))


@tool
async def compute_piotroski_score(fundamentals_json: str) -> str:
    """Compute Piotroski F-Score from fundamental data.

    Args:
        fundamentals_json: JSON string of fundamental data fields.
    """
    try:
        data = json.loads(fundamentals_json)
        result = score_piotroski_f(data)
        return _json_dumps(result)
    except Exception as exc:
        return _tool_error("compute_piotroski_score", str(exc))


@tool
async def compute_altman_z(fundamentals_json: str) -> str:
    """Compute Altman Z-Score from fundamental data.

    Args:
        fundamentals_json: JSON string of fundamental data fields.
    """
    try:
        data = json.loads(fundamentals_json)
        result = score_altman_z(data)
        return _json_dumps(result)
    except Exception as exc:
        return _tool_error("compute_altman_z", str(exc))


# ── Provider-dependent tool implementations (bare, bound at runtime) ─────────


async def _get_stock_quote(provider: Any, symbol: str) -> str:
    """Fetch the current stock quote for a symbol.

    Args:
        symbol: Stock ticker symbol (e.g. AAPL, MSFT).
    """
    try:
        result = await get_quote(provider, symbol)
        return _json_dumps(result)
    except Exception as exc:
        return _tool_error("get_stock_quote", str(exc))


async def _get_ohlcv_data(
    provider: Any, symbol: str, period: str = "1y", interval: str = "1d",
) -> str:
    """Fetch OHLCV price history for a symbol.

    Args:
        symbol: Stock ticker symbol.
        period: Time period — 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y.
        interval: Bar interval — 1m, 5m, 15m, 30m, 60m, 1d, 1wk, 1mo.
    """
    try:
        df = await get_ohlcv(provider, symbol, period=period, interval=interval)
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
    except Exception as exc:
        return _tool_error("get_ohlcv_data", str(exc))


async def _get_stock_fundamentals(provider: Any, symbol: str) -> str:
    """Fetch fundamental data for a symbol.

    Args:
        symbol: Stock ticker symbol.
    """
    try:
        result = await get_fundamentals(provider, symbol)
        return _json_dumps(result)
    except Exception as exc:
        return _tool_error("get_stock_fundamentals", str(exc))


async def _get_stock_news(provider: Any, symbol: str, days: int = 7) -> str:
    """Fetch recent news headlines for a symbol.

    Args:
        symbol: Stock ticker symbol.
        days: Number of days to look back.
    """
    try:
        result = await get_news(provider, symbol, days=days)
        return _json_dumps(result)
    except Exception as exc:
        return _tool_error("get_stock_news", str(exc))


async def _search_stock_symbols(provider: Any, query: str) -> str:
    """Search for stock symbols by company name.

    Args:
        query: Company name or partial ticker to search for.
    """
    try:
        result = await search_symbols(provider, query)
        return _json_dumps(result)
    except Exception as exc:
        return _tool_error("search_stock_symbols", str(exc))


async def _compute_technical_indicators(provider: Any, symbol: str, indicators: str) -> str:
    """Compute technical indicators for a symbol.

    Args:
        symbol: Stock ticker symbol.
        indicators: Comma-separated list of indicators such as
            sma_20, ema_50, rsi_14, macd, bbands, atr_14, adx_14, obv,
            stoch_k, stoch_d, vwap, supertrend.
    """
    try:
        df = await get_ohlcv(provider, symbol, period="1y")
        indicator_list = [i.strip() for i in indicators.split(",")]
        result_df = compute_indicators(df, indicator_list)
        cols = [c for c in result_df.columns if c not in {"Open", "High", "Low", "Close", "Volume"}]
        latest = result_df.iloc[-1][["Close"] + cols]
        return _json_dumps({"symbol": symbol, "latest": latest.round(4).to_dict()})
    except Exception as exc:
        return _tool_error("compute_technical_indicators", str(exc))


async def _detect_chart_patterns(provider: Any, symbol: str) -> str:
    """Detect candlestick patterns for a symbol.

    Args:
        symbol: Stock ticker symbol.
    """
    try:
        df = await get_ohlcv(provider, symbol, period="3mo")
        patterns = detect_patterns(df)
        return _json_dumps({"symbol": symbol, "patterns": patterns[:10]})
    except Exception as exc:
        return _tool_error("detect_chart_patterns", str(exc))


async def _get_support_resistance(provider: Any, symbol: str) -> str:
    """Detect support and resistance levels for a symbol.

    Args:
        symbol: Stock ticker symbol.
    """
    try:
        df = await get_ohlcv(provider, symbol, period="6mo")
        levels = detect_support_resistance(df)
        return _json_dumps(levels)
    except Exception as exc:
        return _tool_error("get_support_resistance", str(exc))


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
    try:
        config = BacktestConfig(symbol=symbol.upper(), strategy=strategy, period=period)
        result = await run_backtest(provider, config)
        return format_backtest_result(result)
    except Exception as exc:
        return _tool_error("run_backtest_tool", str(exc))


async def _screen_stocks_tool(
    provider: Any,
    universe: str = "sp500",
    criteria: str = "",
    sort_by: str = "market_cap",
    limit: int = 20,
) -> str:
    """Screen stocks by fundamental and technical criteria.

    Args:
        universe: Universe to screen — sp500, nasdaq100, russell2000.
        criteria: JSON string of criteria, e.g. '{"pe_lt": 15, "roe_gt": 0.20}'.
        sort_by: Field to sort by.
        limit: Maximum results to return.
    """
    try:
        crit = json.loads(criteria) if criteria else {}
        df = await screen_stocks(
            provider, universe=universe, criteria=crit, sort_by=sort_by, limit=limit,
        )
        if df.empty:
            return "No stocks matched the criteria."
        return df.to_json(orient="records", indent=2)
    except Exception as exc:
        return _tool_error("screen_stocks_tool", str(exc))


async def _optimize_portfolio_tool(
    provider: Any, symbols: str, method: str = "max_sharpe",
) -> str:
    """Optimize portfolio weights for a list of symbols.

    Args:
        symbols: Comma-separated list of stock symbols.
        method: Optimization method — max_sharpe, min_vol, risk_parity, equal_weight.
    """
    try:
        sym_list = _parse_comma_symbols(symbols)
        result = await optimize_portfolio(provider, sym_list, method=method)
        return _json_dumps(result)
    except Exception as exc:
        return _tool_error("optimize_portfolio_tool", str(exc))


async def _compute_portfolio_risk(provider: Any, symbols: str, weights: str) -> str:
    """Compute portfolio risk metrics.

    Args:
        symbols: Comma-separated list of stock symbols.
        weights: Comma-separated list of weights (must sum to ~1.0).
    """
    try:
        sym_list = _parse_comma_symbols(symbols)
        w_list = _parse_comma_weights(weights)
        weight_dict = dict(zip(sym_list, w_list, strict=False))
        result = await compute_portfolio_metrics(provider, weight_dict)
        return _json_dumps(result)
    except Exception as exc:
        return _tool_error("compute_portfolio_risk", str(exc))


async def _run_monte_carlo(provider: Any, symbols: str, weights: str) -> str:
    """Run Monte Carlo simulation for a portfolio.

    Args:
        symbols: Comma-separated list of stock symbols.
        weights: Comma-separated list of weights.
    """
    try:
        sym_list = _parse_comma_symbols(symbols)
        w_list = _parse_comma_weights(weights)
        weight_dict = dict(zip(sym_list, w_list, strict=False))
        result = await monte_carlo_simulation(provider, weight_dict)
        return _json_dumps(result)
    except Exception as exc:
        return _tool_error("run_monte_carlo", str(exc))


async def _compare_peers(provider: Any, symbols: str) -> str:
    """Compare fundamentals across multiple peers.

    Args:
        symbols: Comma-separated list of stock symbols.
    """
    try:
        sym_list = _parse_comma_symbols(symbols)
        fund_map = {}
        for sym in sym_list:
            fund_map[sym] = await get_fundamentals(provider, sym)
        df = peer_comparison(fund_map)
        return df.to_json(orient="index", indent=2)
    except Exception as exc:
        return _tool_error("compare_peers", str(exc))


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
        compute_dcf_valuation,
        compute_piotroski_score,
        compute_altman_z,
    ]

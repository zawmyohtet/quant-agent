"""Tests for tools registry."""
from __future__ import annotations

import asyncio

import pytest

from quantagent.agent.tools_registry import (
    _bind_provider,
    _compute_portfolio_risk,
    _parse_symbols_and_weights,
    _run_monte_carlo,
    _with_timeout,
    build_tool_registry,
)
from quantagent.tui.config import QuantAgentConfig


class _DummyProvider:
    async def get_quote(self, symbol: str) -> dict:
        return {"symbol": symbol, "price": 100.0}

    async def get_ohlcv(self, symbol: str, period: str = "1y", interval: str = "1d") -> None:
        return None

    async def get_fundamentals(self, symbol: str) -> dict:
        return {}

    async def search_symbols(self, query: str) -> list[dict]:
        return []

    async def get_news(self, symbol: str, days: int = 7) -> list[dict]:
        return []

    async def get_earnings_calendar(
        self, symbol: str, lookahead_days: int = 90
    ) -> list[dict]:
        return []

    async def get_sector_performance(self) -> dict:
        return {}

    async def get_economic_indicators(self) -> dict:
        return {}


async def _dummy_tool(provider: _DummyProvider, x: int) -> str:
    """A dummy tool for testing."""
    return f"result_{x}"


def test_build_tool_registry() -> None:
    config = QuantAgentConfig()
    tools = build_tool_registry(config)
    assert len(tools) > 0
    names = [t.name for t in tools]
    assert "get_stock_quote" in names
    assert "get_ohlcv_data" in names
    assert "run_backtest_tool" in names
    assert "optimize_portfolio_tool" in names


def test_bind_provider_creates_tool() -> None:
    provider = _DummyProvider()
    tool = _bind_provider(_dummy_tool, provider)
    assert tool.name == "dummy_tool"


def test_bind_provider_preserves_docstring() -> None:
    provider = _DummyProvider()

    async def tool_with_doc(provider: _DummyProvider, val: str) -> str:
        """My docstring."""
        return val

    tool = _bind_provider(tool_with_doc, provider)
    assert "My docstring." in str(tool)


def test_bind_provider_signature() -> None:
    provider = _DummyProvider()
    tool = _bind_provider(_dummy_tool, provider)
    assert tool.name == "dummy_tool"


@pytest.mark.asyncio
async def test_with_timeout_success() -> None:
    async def _return_val() -> int:
        return 42

    result = await _with_timeout(_return_val(), timeout=5.0)
    assert result == 42


@pytest.mark.asyncio
async def test_with_timeout_timeout() -> None:
    with pytest.raises(TimeoutError):
        await _with_timeout(asyncio.sleep(10.0), timeout=0.01)


@pytest.mark.asyncio
async def test_provider_independent_tools() -> None:
    from quantagent.agent.tools_registry import (
        check_risk_circuit_breaker,
        compute_dcf_valuation,
        journal_log_trade,
        journal_stats,
    )
    assert journal_log_trade.name == "journal_log_trade"
    assert journal_stats.name == "journal_stats"
    assert check_risk_circuit_breaker.name == "check_risk_circuit_breaker"
    assert compute_dcf_valuation.name == "compute_dcf_valuation"

    from quantagent.agent.tools_registry import journal_open_trades
    trades = await journal_open_trades.ainvoke({})
    assert "no open trades" in trades.lower()


@pytest.mark.asyncio
async def test_journal_history_empty() -> None:
    from quantagent.agent.tools_registry import journal_history
    result = await journal_history.ainvoke({"days": 1})
    assert "No journaled trades" in result


def test_parse_symbols_and_weights_success() -> None:
    result = _parse_symbols_and_weights("AAPL, MSFT", "0.6,0.4")
    assert result == {"AAPL": 0.6, "MSFT": 0.4}


def test_parse_symbols_and_weights_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="same number of comma-separated entries"):
        _parse_symbols_and_weights("AAPL,MSFT,GOOG", "0.5,0.5")


@pytest.mark.asyncio
async def test_compute_portfolio_risk_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="same number of comma-separated entries"):
        await _compute_portfolio_risk(None, "AAPL,MSFT,GOOG", "0.5,0.5")


@pytest.mark.asyncio
async def test_run_monte_carlo_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="same number of comma-separated entries"):
        await _run_monte_carlo(None, "AAPL,MSFT", "1.0")

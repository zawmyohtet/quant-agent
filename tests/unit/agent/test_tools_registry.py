"""Tests for tools registry."""
from __future__ import annotations

from quantagent.agent.tools_registry import build_tool_registry
from quantagent.tui.config import QuantAgentConfig


def test_build_tool_registry():
    config = QuantAgentConfig()
    tools = build_tool_registry(config)
    assert len(tools) > 0
    names = [t.name for t in tools]
    assert "get_stock_quote" in names
    assert "get_ohlcv_data" in names
    assert "run_backtest_tool" in names
    assert "optimize_portfolio_tool" in names

"""Tests for StatusBar."""
from __future__ import annotations

from quantagent.tui.config import QuantAgentConfig
from quantagent.tui.session_state import SessionState
from quantagent.tui.widgets.status_bar import StatusBar


class TestStatusBar:
    def test_idle_state(self) -> None:
        config = QuantAgentConfig(model="openai:gpt-4o", provider="yfinance")
        state = SessionState(config=config)
        bar = StatusBar(state)
        bar.refresh_state()
        text = str(bar.render())
        assert "openai:gpt-4o" in text
        assert "yfinance" in text
        assert "Running" not in text
        assert "esc interrupt" not in text

    def test_running_state(self) -> None:
        config = QuantAgentConfig(model="openai:gpt-4o", provider="yfinance")
        state = SessionState(config=config)
        state.is_running = True
        bar = StatusBar(state)
        bar.refresh_state()
        text = str(bar.render())
        assert "Running" in text
        assert "esc interrupt" in text

    def test_running_indicator_resets_when_idle(self) -> None:
        config = QuantAgentConfig(model="openai:gpt-4o", provider="yfinance")
        state = SessionState(config=config)
        state.is_running = True
        bar = StatusBar(state)
        bar.refresh_state()
        assert "Running" in str(bar.render())

        state.is_running = False
        bar.refresh_state()
        text = str(bar.render())
        assert "Running" not in text
        assert "esc interrupt" not in text

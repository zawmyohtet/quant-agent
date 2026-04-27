"""Tests for StatusBar."""
from __future__ import annotations

from unittest.mock import MagicMock

from quantagent.tui.config import QuantAgentConfig
from quantagent.tui.session_state import SessionState
from quantagent.tui.widgets.status_bar import StatusBar


class TestStatusBar:
    def _compose_bar(self, state: SessionState) -> StatusBar:
        """Create and compose a StatusBar so its child widgets are accessible."""
        bar = StatusBar(state)
        bar._info = MagicMock()
        return bar

    def test_idle_state(self) -> None:
        config = QuantAgentConfig(model="openai:gpt-4o", provider="yfinance")
        state = SessionState(config=config)
        bar = self._compose_bar(state)
        bar.refresh_state()
        text = str(bar._info.update.call_args)
        assert "openai:gpt-4o" in text
        assert "yfinance" in text

    def test_running_state_shows_info_only(self) -> None:
        config = QuantAgentConfig(model="openai:gpt-4o", provider="yfinance")
        state = SessionState(config=config)
        state.is_running = True
        bar = self._compose_bar(state)
        bar.refresh_state()
        text = str(bar._info.update.call_args)
        assert "openai:gpt-4o" in text
        assert "yfinance" in text

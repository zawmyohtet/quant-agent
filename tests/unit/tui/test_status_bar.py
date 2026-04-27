"""Tests for StatusBar with LoadingIndicator."""
from __future__ import annotations

from unittest.mock import MagicMock

from quantagent.tui.config import QuantAgentConfig
from quantagent.tui.session_state import SessionState
from quantagent.tui.widgets.status_bar import StatusBar


class TestStatusBar:
    def _compose_bar(self, state: SessionState) -> StatusBar:
        """Create and compose a StatusBar so its child widgets are accessible."""
        bar = StatusBar(state)
        # Manually compose children (normally done by the framework on mount)
        bar._info = MagicMock()
        bar._indicator = MagicMock()
        bar._indicator.display = False
        bar._hint = MagicMock()
        bar._hint.display = False
        return bar

    def test_idle_state(self) -> None:
        config = QuantAgentConfig(model="openai:gpt-4o", provider="yfinance")
        state = SessionState(config=config)
        bar = self._compose_bar(state)
        bar.refresh_state()
        text = str(bar._info.update.call_args)
        assert "openai:gpt-4o" in text
        assert "yfinance" in text
        assert bar._indicator.display is False
        assert bar._hint.display is False

    def test_running_state(self) -> None:
        config = QuantAgentConfig(model="openai:gpt-4o", provider="yfinance")
        state = SessionState(config=config)
        state.is_running = True
        bar = self._compose_bar(state)
        bar.refresh_state()
        assert bar._indicator.display is True
        assert bar._hint.display is True

    def test_running_indicator_resets_when_idle(self) -> None:
        config = QuantAgentConfig(model="openai:gpt-4o", provider="yfinance")
        state = SessionState(config=config)
        state.is_running = True
        bar = self._compose_bar(state)
        bar.refresh_state()
        assert bar._indicator.display is True

        state.is_running = False
        bar.refresh_state()
        assert bar._indicator.display is False
        assert bar._hint.display is False

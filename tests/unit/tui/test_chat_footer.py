"""Tests for ChatFooter with LoadingIndicator."""
from __future__ import annotations

from unittest.mock import MagicMock

from quantagent.tui.config import QuantAgentConfig
from quantagent.tui.session_state import SessionState
from quantagent.tui.widgets.chat_footer import ChatFooter


class TestChatFooter:
    def _compose_footer(self, state: SessionState) -> ChatFooter:
        """Create and compose a ChatFooter so its child widgets are accessible."""
        footer = ChatFooter(state)
        footer._indicator = MagicMock()
        footer._indicator.display = False
        footer._hint = MagicMock()
        footer._hint.display = False
        return footer

    def test_idle_state(self) -> None:
        config = QuantAgentConfig(model="openai:gpt-4o", provider="yfinance")
        state = SessionState(config=config)
        footer = self._compose_footer(state)
        footer.refresh_state()
        assert footer._indicator.display is False
        assert footer._hint.display is False

    def test_running_state(self) -> None:
        config = QuantAgentConfig(model="openai:gpt-4o", provider="yfinance")
        state = SessionState(config=config)
        state.is_running = True
        footer = self._compose_footer(state)
        footer.refresh_state()
        assert footer._indicator.display is True
        assert footer._hint.display is True

    def test_running_indicator_resets_when_idle(self) -> None:
        config = QuantAgentConfig(model="openai:gpt-4o", provider="yfinance")
        state = SessionState(config=config)
        state.is_running = True
        footer = self._compose_footer(state)
        footer.refresh_state()
        assert footer._indicator.display is True

        state.is_running = False
        footer.refresh_state()
        assert footer._indicator.display is False
        assert footer._hint.display is False

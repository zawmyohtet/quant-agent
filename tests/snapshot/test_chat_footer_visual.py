"""Snapshot tests for ChatFooter visual states."""
from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Vertical

from quantagent.tui.config import QuantAgentConfig
from quantagent.tui.session_state import SessionState
from quantagent.tui.widgets.chat_footer import ChatFooter


class _IdleFooterApp(App):
    """Minimal app showing ChatFooter in idle state."""

    def compose(self) -> ComposeResult:
        state = SessionState(
            config=QuantAgentConfig(model="openai:gpt-4o", provider="yfinance"),
            is_running=False,
        )
        yield Vertical(ChatFooter(state, id="chat-footer"))


class _RunningFooterApp(App):
    """Minimal app showing ChatFooter in running state."""

    def compose(self) -> ComposeResult:
        state = SessionState(
            config=QuantAgentConfig(model="openai:gpt-4o", provider="yfinance"),
            is_running=True,
        )
        yield Vertical(ChatFooter(state, id="chat-footer"))


class TestChatFooterSnapshots:
    def test_idle_state_snapshot(self, snap_compare: object) -> None:
        assert snap_compare(_IdleFooterApp())

    def test_running_state_snapshot(self, snap_compare: object) -> None:
        assert snap_compare(_RunningFooterApp())

"""Snapshot tests for QuantAgentApp full layout visual states."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult

from quantagent.tui.config import QuantAgentConfig
from quantagent.tui.session_state import SessionState
from quantagent.tui.widgets.chat_footer import ChatFooter
from quantagent.tui.widgets.chat_input import ChatInput
from quantagent.tui.widgets.message_view import MessageView
from quantagent.tui.widgets.status_bar import StatusBar
from tests.snapshot._base import SnapshotApp

_PROJECT_ROOT = Path(__file__).parent.parent.parent


class _AppIdleLayout(SnapshotApp):
    """Full app layout in idle state for snapshot."""

    CSS_PATH = _PROJECT_ROOT / "quantagent" / "tui" / "app.tcss"

    def compose(self) -> ComposeResult:
        state = SessionState(
            config=QuantAgentConfig(model="openai:gpt-4o", provider="yfinance"),
            thread_id="test-thread-1234",
            token_count=0,
            is_running=False,
        )
        yield MessageView(id="messages")
        yield StatusBar(state, id="status-bar")
        yield ChatInput(id="chat-input")
        yield ChatFooter(state, id="chat-footer")


class TestAppLayoutSnapshots:
    """Visual regression tests for full app layout."""

    def test_default_layout(self, snap_compare: object) -> None:
        assert snap_compare(_AppIdleLayout())

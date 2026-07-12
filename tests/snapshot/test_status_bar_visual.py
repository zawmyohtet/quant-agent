"""Snapshot tests for StatusBar visual states."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical

from quantagent.tui.config import QuantAgentConfig
from quantagent.tui.session_state import SessionState
from quantagent.tui.widgets.status_bar import StatusBar
from tests.snapshot._base import SnapshotApp


class _StatusBarApp(SnapshotApp):
    """Minimal app showing StatusBar with default state."""

    def compose(self) -> ComposeResult:
        state = SessionState(
            config=QuantAgentConfig(model="openai:gpt-4o", provider="yfinance"),
            thread_id="test-thread-1234",
            token_count=0,
        )
        yield Vertical(StatusBar(state, id="status-bar"))


class TestStatusBarSnapshots:
    """Visual regression tests for StatusBar."""

    def test_default_state(self, snap_compare: object) -> None:
        assert snap_compare(_StatusBarApp())

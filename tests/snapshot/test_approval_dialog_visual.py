"""Snapshot tests for ApprovalDialog visual states."""
from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult

from quantagent.tui.widgets.approval_dialog import ApprovalDialog


class _ApprovalDialogApp(App):
    """Minimal app showing ApprovalDialog with sample tool call."""

    def compose(self) -> ComposeResult:
        future: asyncio.Future[bool] = asyncio.get_event_loop().create_future()
        yield ApprovalDialog(
            tool_name="get_ohlcv",
            args={"symbol": "AAPL", "period": "1y"},
            future=future,
        )


class TestApprovalDialogSnapshots:
    """Visual regression tests for ApprovalDialog."""

    def test_default_state(self, snap_compare: object) -> None:
        assert snap_compare(_ApprovalDialogApp())

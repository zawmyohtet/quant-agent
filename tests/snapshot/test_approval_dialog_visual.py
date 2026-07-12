"""Snapshot tests for ApprovalDialog visual states."""

from __future__ import annotations

import asyncio

from quantagent.tui.widgets.approval_dialog import ApprovalDialog
from tests.snapshot._base import SnapshotApp


class _ApprovalDialogApp(SnapshotApp):
    """Minimal app showing ApprovalDialog with a sample tool call."""

    def on_mount(self) -> None:
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self.push_screen(
            ApprovalDialog(
                tool_name="get_ohlcv",
                args={"symbol": "AAPL", "period": "1y"},
                future=future,
            )
        )


class TestApprovalDialogSnapshots:
    """Visual regression tests for ApprovalDialog."""

    def test_default_state(self, snap_compare: object) -> None:
        assert snap_compare(_ApprovalDialogApp())

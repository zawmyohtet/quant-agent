"""Tests for ApprovalDialog behaviour."""
from __future__ import annotations

import asyncio

import pytest

from quantagent.tui.widgets.approval_dialog import ApprovalDialog


@pytest.mark.asyncio
async def test_on_unmount_rejects_pending_future() -> None:
    loop = asyncio.get_running_loop()
    future: asyncio.Future[bool] = loop.create_future()
    dialog = ApprovalDialog("tool_x", {"a": 1}, future)

    await dialog.on_unmount()

    assert future.done() is True
    assert future.result() is False

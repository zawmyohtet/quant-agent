"""Tests for MessageView."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from quantagent.tui.widgets.message_view import MessageView


def _make_view() -> MessageView:
    """Return a MessageView with mocked DOM operations."""
    view = MessageView()
    view.mount = MagicMock()  # type: ignore[method-assign]
    view.scroll_end = MagicMock()  # type: ignore[method-assign]

    def _mocked_render(entry: Any) -> Any:
        widget = MagicMock()
        widget.remove = MagicMock()  # type: ignore[method-assign]
        return widget

    view._render_entry = _mocked_render  # type: ignore[method-assign]
    return view


class TestMessageView:
    def test_clear_resets_state(self) -> None:
        view = _make_view()
        view.add_user_message("hello")
        view.clear()
        assert view._all_entries == []
        assert view._agent_buffer_id is None


class TestToolProgress:
    def test_updates_running_tool_line(self) -> None:
        view = _make_view()
        view.add_tool_call("c1", "run_workflow_tool", {})
        view.update_tool_progress("c1", "step 2/4: sectors…")
        entry = view._find_entry("c1")
        assert entry is not None
        assert entry.content == "run_workflow_tool — step 2/4: sectors…"
        assert entry.kind == "tool_start"

    def test_ignores_completed_tool(self) -> None:
        view = _make_view()
        view.add_tool_call("c1", "run_workflow_tool", {})
        view.complete_tool_call("c1", "result")
        view.update_tool_progress("c1", "late progress")
        entry = view._find_entry("c1")
        assert entry is not None
        assert entry.content == "run_workflow_tool — done"

    def test_empty_call_id_falls_back_to_latest_running(self) -> None:
        view = _make_view()
        view.add_tool_call("c1", "first_tool", {})
        view.complete_tool_call("c1", "done")
        view.add_tool_call("c2", "second_tool", {})
        view.update_tool_progress("", "halfway")
        entry = view._find_entry("c2")
        assert entry is not None
        assert entry.content == "second_tool — halfway"

    def test_no_running_tool_is_noop(self) -> None:
        view = _make_view()
        view.add_user_message("hi")
        view.update_tool_progress("", "orphan progress")  # must not raise

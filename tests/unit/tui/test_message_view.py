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
    # _render_entry returns a Static; mock its remove() to avoid app context
    original_render = view._render_entry

    def _mocked_render(entry: Any) -> Any:
        widget = original_render(entry)
        widget.remove = MagicMock()  # type: ignore[method-assign]
        return widget

    view._render_entry = _mocked_render  # type: ignore[method-assign]
    return view


class TestMessageView:
    def test_show_thinking_creates_entry(self) -> None:
        view = _make_view()
        mid = view.show_thinking()
        assert mid is not None
        assert view._thinking_id == mid
        assert any(e.kind == "thinking" for e in view._all_entries)

    def test_hide_thinking_removes_entry(self) -> None:
        view = _make_view()
        mid = view.show_thinking()
        view.hide_thinking(mid)
        assert view._thinking_id is None
        assert not any(e.message_id == mid for e in view._all_entries)

    def test_hide_thinking_if_present_cleans_up(self) -> None:
        view = _make_view()
        mid = view.show_thinking()
        view.hide_thinking_if_present()
        assert view._thinking_id is None
        assert not any(e.message_id == mid for e in view._all_entries)

    def test_hide_thinking_if_present_no_op_when_absent(self) -> None:
        view = _make_view()
        view.hide_thinking_if_present()
        assert view._thinking_id is None
        assert view._all_entries == []

    def test_clear_resets_state(self) -> None:
        view = _make_view()
        view.show_thinking()
        view.add_user_message("hello")
        view.clear()
        assert view._all_entries == []
        assert view._thinking_id is None
        assert view._agent_buffer_id is None

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

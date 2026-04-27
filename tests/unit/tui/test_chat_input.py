from __future__ import annotations

from typing import Any

import pytest

from quantagent.tui.widgets.chat_input import ChatInput


class FakeDropdown:
    """Minimal stand-in for ListView to test dropdown logic."""

    def __init__(self) -> None:
        self.display = False
        self._items: list[object] = []

    def clear(self) -> None:
        self._items = []

    def append(self, item: object) -> None:
        self._items.append(item)

    @property
    def children(self) -> list[object]:
        return self._items


class TestChatInputDropdown:
    """Unit tests for slash-command autocomplete behaviour."""

    @pytest.fixture
    def widget(self) -> ChatInput:
        w = ChatInput()
        w._dropdown = FakeDropdown()  # type: ignore[assignment]
        return w

    def test_shows_for_partial_command(self, widget: ChatInput) -> None:
        widget._update_dropdown("/ana")
        assert widget._dropdown.display is True
        assert len(widget._dropdown.children) > 0

    def test_hides_for_unknown_command(self, widget: ChatInput) -> None:
        widget._update_dropdown("/notacommand")
        assert widget._dropdown.display is False
        assert len(widget._dropdown.children) == 0

    def test_shows_with_single_argument(self, widget: ChatInput) -> None:
        widget._update_dropdown("/analyze AAPL")
        assert widget._dropdown.display is True
        assert len(widget._dropdown.children) > 0

    def test_shows_with_multiple_arguments(self, widget: ChatInput) -> None:
        widget._update_dropdown("/backtest AAPL momentum")
        assert widget._dropdown.display is True
        assert len(widget._dropdown.children) > 0

    def test_shows_for_exact_command_with_trailing_space(self, widget: ChatInput) -> None:
        widget._update_dropdown("/analyze ")
        assert widget._dropdown.display is True
        assert len(widget._dropdown.children) > 0

    def test_hides_for_space_only(self, widget: ChatInput) -> None:
        widget._update_dropdown("/ ")
        assert widget._dropdown.display is False
        assert len(widget._dropdown.children) == 0

    def test_hides_for_empty_after_slash(self, widget: ChatInput) -> None:
        widget._update_dropdown("/")
        assert widget._dropdown.display is False
        assert len(widget._dropdown.children) == 0

    def test_matches_aliases(self, widget: ChatInput) -> None:
        # No aliases are registered by default, but this guards against regression
        widget._update_dropdown("/h")
        assert widget._dropdown.display is True
        assert any(getattr(item, "command_name", "") == "help" for item in widget._dropdown.children)


class TestChatInputAutocomplete:
    """Unit tests for ChatInput autocomplete application."""

    async def test_apply_autocomplete_moves_cursor_to_end(self) -> None:
        from textual.app import App

        class _App(App[None]):
            def compose(self) -> Any:
                yield ChatInput()

        app = _App()
        async with app.run_test():
            widget = app.query_one(ChatInput)
            # Simulate user having typed "/ana" (cursor lands at end after first value set)
            widget._input.value = "/ana"
            assert widget._input.cursor_position == 4
            widget._apply_autocomplete("analyze")
            assert widget._input.value == "/analyze "
            assert widget._input.cursor_position == len("/analyze ")

    async def test_apply_autocomplete_keeps_cursor_at_end_after_focus(self) -> None:
        from textual.app import App

        class _App(App[None]):
            def compose(self) -> Any:
                yield ChatInput()

        app = _App()
        async with app.run_test():
            widget = app.query_one(ChatInput)
            widget._input.value = "/sc"
            assert widget._input.cursor_position == 3
            widget._apply_autocomplete("screen")
            assert widget._input.value == "/screen "
            assert widget._input.cursor_position == len("/screen ")


class TestChatInputWidget:
    """Unit tests for ChatInput widget configuration."""

    def test_input_does_not_select_on_focus(self) -> None:
        widget = ChatInput()
        assert widget._input.select_on_focus is False

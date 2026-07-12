from __future__ import annotations

from typing import Any

import pytest

from quantagent.tui.commands import REGISTRY
from quantagent.tui.widgets.chat_input import ChatInput, Suggestion


class FakeDropdown:
    """Minimal stand-in for ListView to test dropdown logic."""

    def __init__(self) -> None:
        self.display = False
        self.index: int | None = None
        self._items: list[object] = []

    def clear(self) -> None:
        self._items = []

    def append(self, item: object) -> None:
        self._items.append(item)

    @property
    def children(self) -> list[object]:
        return self._items


def _insert_texts(widget: ChatInput) -> list[str]:
    return [item.suggestion.insert_text for item in widget._dropdown.children]


def _command_names(widget: ChatInput) -> list[str]:
    # Command suggestions insert "/<name> "; extract the name token.
    return [text.strip().lstrip("/") for text in _insert_texts(widget)]


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

    def test_hides_with_single_argument(self, widget: ChatInput) -> None:
        widget._update_dropdown("/analyze AAPL")
        assert widget._dropdown.display is False

    def test_hides_with_multiple_arguments(self, widget: ChatInput) -> None:
        widget._update_dropdown("/backtest AAPL momentum")
        assert widget._dropdown.display is False

    def test_hides_for_exact_command_with_trailing_space(self, widget: ChatInput) -> None:
        widget._update_dropdown("/analyze ")
        assert widget._dropdown.display is False

    def test_hides_for_space_only(self, widget: ChatInput) -> None:
        widget._update_dropdown("/ ")
        assert widget._dropdown.display is False

    def test_shows_all_commands_for_bare_slash(self, widget: ChatInput) -> None:
        widget._update_dropdown("/")
        assert widget._dropdown.display is True
        assert len(widget._dropdown.children) == len(REGISTRY)

    def test_matches_aliases(self, widget: ChatInput) -> None:
        # No aliases are registered by default, but this guards against regression
        widget._update_dropdown("/h")
        assert widget._dropdown.display is True
        assert "help" in _command_names(widget)

    def test_matches_substring(self, widget: ChatInput) -> None:
        # No command starts with "flow", but workflow/workflows contain it
        widget._update_dropdown("/flow")
        assert widget._dropdown.display is True
        names = _command_names(widget)
        assert "workflow" in names
        assert "workflows" in names

    def test_prefix_matches_rank_before_substring_matches(self, widget: ChatInput) -> None:
        widget._update_dropdown("/re")
        names = _command_names(widget)
        prefix_names = [n for n in names if n.startswith("re")]
        substr_names = [n for n in names if not n.startswith("re")]
        assert prefix_names, "expected prefix matches for /re"
        assert substr_names, "expected substring matches for /re"
        assert names == prefix_names + substr_names

    def test_resets_highlight_on_refresh(self, widget: ChatInput) -> None:
        widget._update_dropdown("/")
        widget._dropdown.index = 3
        widget._update_dropdown("/m")
        assert widget._dropdown.index is None


class TestArgumentAutocomplete:
    """Unit tests for first-argument completion (e.g. /theme <name>)."""

    @pytest.fixture
    def widget(self) -> ChatInput:
        w = ChatInput()
        w._dropdown = FakeDropdown()  # type: ignore[assignment]
        return w

    def test_shows_all_values_after_command(self, widget: ChatInput) -> None:
        widget._update_dropdown("/theme ")
        assert widget._dropdown.display is True
        assert "/theme nord " in _insert_texts(widget)

    def test_filters_by_partial_argument(self, widget: ChatInput) -> None:
        widget._update_dropdown("/theme nor")
        assert widget._dropdown.display is True
        texts = _insert_texts(widget)
        assert "/theme nord " in texts
        assert all("nor" in text for text in texts)

    def test_hides_for_unknown_value(self, widget: ChatInput) -> None:
        widget._update_dropdown("/theme zzz")
        assert widget._dropdown.display is False

    def test_hides_after_first_argument_complete(self, widget: ChatInput) -> None:
        widget._update_dropdown("/theme nord extra")
        assert widget._dropdown.display is False


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
            widget._apply_autocomplete(Suggestion(label="/analyze", insert_text="/analyze "))
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
            widget._apply_autocomplete(Suggestion(label="/screen", insert_text="/screen "))
            assert widget._input.value == "/screen "
            assert widget._input.cursor_position == len("/screen ")


class TestChatInputNavigation:
    """Pilot-driven tests for keyboard navigation of the dropdown."""

    @staticmethod
    def _make_app() -> Any:
        from textual.app import App

        class _App(App[None]):
            def __init__(self) -> None:
                super().__init__()
                self.submitted: list[str] = []

            def compose(self) -> Any:
                yield ChatInput()

            def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
                self.submitted.append(event.value)

        return _App()

    async def test_down_highlights_first_item_and_keeps_input_focus(self) -> None:
        app = self._make_app()
        async with app.run_test() as pilot:
            widget = app.query_one(ChatInput)
            await pilot.press("/", "m", "o")
            assert widget._dropdown.display is True
            assert widget._dropdown.index is None
            await pilot.press("down")
            assert widget._dropdown.index == 0
            assert app.focused is widget._input

    async def test_up_and_down_navigate_highlight(self) -> None:
        app = self._make_app()
        async with app.run_test() as pilot:
            widget = app.query_one(ChatInput)
            await pilot.press("/")
            await pilot.press("down", "down")
            assert widget._dropdown.index == 1
            await pilot.press("up")
            assert widget._dropdown.index == 0
            await pilot.press("up")
            assert widget._dropdown.index is None

    async def test_enter_completes_highlighted_without_submitting(self) -> None:
        app = self._make_app()
        async with app.run_test() as pilot:
            widget = app.query_one(ChatInput)
            await pilot.press("/", "m", "o")
            await pilot.press("down", "enter")
            assert widget._input.value == "/model "
            assert widget._dropdown.display is False
            assert app.submitted == []

    async def test_enter_without_highlight_submits(self) -> None:
        app = self._make_app()
        async with app.run_test() as pilot:
            widget = app.query_one(ChatInput)
            await pilot.press("/", "m", "o", "d", "e", "l", "space", "x")
            assert widget._dropdown.display is False
            await pilot.press("enter")
            assert app.submitted == ["/model x"]
            assert widget._input.value == ""

    async def test_tab_completes_first_when_nothing_highlighted(self) -> None:
        app = self._make_app()
        async with app.run_test() as pilot:
            widget = app.query_one(ChatInput)
            await pilot.press("/", "m", "o")
            await pilot.press("tab")
            assert widget._input.value == "/model "
            assert widget._dropdown.display is False

    async def test_escape_hides_dropdown_and_keeps_text(self) -> None:
        app = self._make_app()
        async with app.run_test() as pilot:
            widget = app.query_one(ChatInput)
            await pilot.press("/", "m", "o")
            assert widget._dropdown.display is True
            await pilot.press("escape")
            assert widget._dropdown.display is False
            assert widget._input.value == "/mo"


class TestChatInputWidget:
    """Unit tests for ChatInput widget configuration."""

    def test_input_does_not_select_on_focus(self) -> None:
        widget = ChatInput()
        assert widget._input.select_on_focus is False

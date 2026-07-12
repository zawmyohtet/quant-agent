"""Snapshot tests for ChatInput visual states."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical

from quantagent.tui.widgets.chat_input import ChatInput
from tests.snapshot._base import SnapshotApp


class _ChatInputIdleApp(SnapshotApp):
    """Minimal app showing ChatInput in idle state."""

    def compose(self) -> ComposeResult:
        yield Vertical(ChatInput(id="chat-input"))


class _ChatInputWithTextApp(SnapshotApp):
    """Minimal app showing ChatInput with user-typed text."""

    def compose(self) -> ComposeResult:
        yield Vertical(ChatInput(id="chat-input"))

    async def on_mount(self) -> None:
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input._input.value = "analysis AAPL"


class _ChatInputAutocompleteApp(SnapshotApp):
    """Minimal app showing ChatInput with autocomplete dropdown visible."""

    def compose(self) -> ComposeResult:
        yield Vertical(ChatInput(id="chat-input"))

    async def on_mount(self) -> None:
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input._input.value = "/ana"


class TestChatInputSnapshots:
    """Visual regression tests for ChatInput."""

    def test_idle_state(self, snap_compare: object) -> None:
        assert snap_compare(_ChatInputIdleApp())

    def test_with_text(self, snap_compare: object) -> None:
        assert snap_compare(_ChatInputWithTextApp())

    def test_autocomplete_dropdown(self, snap_compare: object) -> None:
        assert snap_compare(_ChatInputAutocompleteApp())

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Key
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Input, ListItem, ListView, Static

from quantagent.tui.commands import REGISTRY

logger = logging.getLogger(__name__)


@dataclass
class Suggestion:
    """A single autocomplete suggestion."""

    label: str
    command_name: str


class ChatInput(Vertical):
    """Multi-line input bar with slash command autocomplete."""

    class Submitted(Message):
        """Message emitted when the user submits input."""

        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    value: reactive[str] = reactive("")

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._input = Input(placeholder="Type a message or /help", id="chat-input-field")
        self._dropdown = ListView(id="chat-input-dropdown")
        self._dropdown.display = False

    def compose(self) -> ComposeResult:
        yield self._input
        yield self._dropdown

    def on_mount(self) -> None:
        self._input.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self.value = event.value
        if event.value.startswith("/"):
            self._update_dropdown(event.value)
        else:
            self._dropdown.display = False

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = self._input.value.strip()
        if text:
            self.post_message(self.Submitted(value=text))
            self._input.value = ""
            self.value = ""
        self._dropdown.display = False

    def on_key(self, event: Key) -> None:
        if event.key == "tab":
            event.stop()
            self._autocomplete()
        elif event.key == "escape":
            self._dropdown.display = False
        elif event.key == "down" and self._dropdown.display:
            event.stop()
            self._dropdown.focus()
        elif event.key == "enter" and event.is_printable:
            # Let Input handle normal Enter
            pass

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if hasattr(item, "command_name"):
            self._input.value = f"/{item.command_name} "
            self._input.focus()
        self._dropdown.display = False

    def _update_dropdown(self, text: str) -> None:
        prefix = text[1:].lower()
        matches = [
            cmd
            for cmd in REGISTRY
            if cmd.name.startswith(prefix) or any(alias.startswith(prefix) for alias in cmd.aliases)
        ]
        if not matches:
            self._dropdown.display = False
            return

        self._dropdown.clear()
        for cmd in matches[:8]:
            item = ListItem(Static(f"/{cmd.name} — {cmd.description}"))
            item.command_name = cmd.name  # type: ignore[attr-defined]
            self._dropdown.append(item)
        self._dropdown.display = True

    def _autocomplete(self) -> None:
        if not self._dropdown.display:
            return
        selected = self._dropdown.highlighted_child
        if selected and hasattr(selected, "command_name"):
            self._input.value = f"/{selected.command_name} "
            self._input.focus()
            self._dropdown.display = False
        elif self._dropdown.children:
            first = self._dropdown.children[0]
            if hasattr(first, "command_name"):
                self._input.value = f"/{first.command_name} "
                self._input.focus()
                self._dropdown.display = False

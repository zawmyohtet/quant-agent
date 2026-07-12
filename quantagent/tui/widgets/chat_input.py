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


class _CommandInput(Input):
    """Input that lets the parent ChatInput consume dropdown-navigation keys."""

    def on_key(self, event: Key) -> None:
        chat = self.parent
        if isinstance(chat, ChatInput) and chat.handle_dropdown_key(event.key):
            event.stop()
            event.prevent_default()


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
        self._input = _CommandInput(
            placeholder="Type a message or /help",
            id="chat-input-field",
            select_on_focus=False,
        )
        self._dropdown = ListView(id="chat-input-dropdown")
        self._dropdown.display = False
        self._dropdown.can_focus = False

    def compose(self) -> ComposeResult:
        yield self._dropdown
        yield self._input

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

    def handle_dropdown_key(self, key: str) -> bool:
        """Handle a navigation key for the dropdown. Returns True if consumed."""
        if not self._dropdown.display:
            return False
        if key == "down":
            count = len(self._dropdown.children)
            if count:
                index = self._dropdown.index
                self._dropdown.index = 0 if index is None else min(index + 1, count - 1)
            return True
        if key == "up":
            index = self._dropdown.index
            if index is None:
                return False
            self._dropdown.index = None if index == 0 else index - 1
            return True
        if key == "enter":
            if self._dropdown.index is None:
                return False
            selected = self._dropdown.highlighted_child
            if selected is not None and hasattr(selected, "command_name"):
                self._apply_autocomplete(selected.command_name)
            self._dropdown.display = False
            return True
        if key == "tab":
            self._autocomplete()
            return True
        if key == "escape":
            self._dropdown.display = False
            return True
        return False

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if hasattr(item, "command_name"):
            self._apply_autocomplete(item.command_name)
        self._dropdown.display = False

    def _apply_autocomplete(self, command_name: str) -> None:
        """Insert the completed command and move cursor to the end."""
        self._input.value = f"/{command_name} "
        self._input.focus()
        self._input.cursor_position = len(self._input.value)

    def _update_dropdown(self, text: str) -> None:
        body = text[1:]
        if " " in body:
            # Command token complete; user is typing arguments.
            self._dropdown.display = False
            return
        prefix = body.lower()
        prefix_matches = [
            cmd
            for cmd in REGISTRY
            if cmd.name.startswith(prefix) or any(alias.startswith(prefix) for alias in cmd.aliases)
        ]
        substr_matches = [
            cmd
            for cmd in REGISTRY
            if cmd not in prefix_matches
            and (prefix in cmd.name or any(prefix in alias for alias in cmd.aliases))
        ]
        matches = prefix_matches + substr_matches
        if not matches:
            self._dropdown.display = False
            return

        self._dropdown.clear()
        for cmd in matches:
            item = ListItem(Static(f"[b]/{cmd.name}[/b] — {cmd.description}", markup=True))
            item.command_name = cmd.name  # type: ignore[attr-defined]
            self._dropdown.append(item)
        self._dropdown.index = None
        self._dropdown.display = True

    def _autocomplete(self) -> None:
        if not self._dropdown.display:
            return
        selected = self._dropdown.highlighted_child
        if selected and hasattr(selected, "command_name"):
            self._apply_autocomplete(selected.command_name)
            self._dropdown.display = False
        elif self._dropdown.children:
            first = self._dropdown.children[0]
            if hasattr(first, "command_name"):
                self._apply_autocomplete(first.command_name)
                self._dropdown.display = False

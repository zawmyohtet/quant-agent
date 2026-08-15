from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import ListItem, ListView, Static, TextArea

from quantagent.tui.commands import REGISTRY, find_command

logger = logging.getLogger(__name__)


@dataclass
class Suggestion:
    """A single autocomplete suggestion."""

    label: str
    insert_text: str
    # Keep the dropdown open (recompute) after applying this suggestion — used
    # when completing a command name that still has sub-commands/args/modes to
    # offer. Terminal suggestions (modes, args with nothing further) leave this
    # False so the menu closes.
    reopen: bool = False


class _CommandTextArea(TextArea):
    """Text area that lets the owning ChatInput consume dropdown-navigation
    keys and submit on Enter instead of inserting a newline."""

    def __init__(self, chat: ChatInput, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._chat = chat

    def on_key(self, event: Key) -> None:
        if self._chat.handle_dropdown_key(event.key):
            event.stop()
            event.prevent_default()
        elif event.key == "enter":
            # Dropdown is closed (or nothing highlighted): submit the message
            # rather than let TextArea insert a literal newline.
            self._chat._submit()
            event.stop()
            event.prevent_default()


class ChatInput(Vertical):
    """Input bar with slash command autocomplete.

    Wraps long text within the box (growing up to a max height) instead of
    scrolling it off-screen horizontally.
    """

    class Submitted(Message):
        """Message emitted when the user submits input."""

        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    value: reactive[str] = reactive("")

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._input = _CommandTextArea(
            self,
            placeholder="Type a message or /help",
            id="chat-input-field",
            soft_wrap=True,
            show_line_numbers=False,
            tab_behavior="focus",
        )
        self._dropdown = ListView(id="chat-input-dropdown")
        self._dropdown.display = False
        self._dropdown.can_focus = False
        # Set when we change the input value programmatically (autocomplete /
        # picker prefill) so the resulting Changed event does not re-open the
        # dropdown we just applied.
        self._suppress_dropdown = False

    def compose(self) -> ComposeResult:
        yield self._dropdown
        with Horizontal(id="chat-input-box"):
            yield Static(">", id="chat-input-prompt")
            yield self._input

    def on_mount(self) -> None:
        self._input.focus()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        text = event.text_area.text
        self.value = text
        if self._suppress_dropdown:
            self._suppress_dropdown = False
            self._dropdown.display = False
            return
        if text.startswith("/"):
            self._update_dropdown(text)
        else:
            self._dropdown.display = False

    def _submit(self) -> None:
        text = self._input.text.strip()
        if text:
            self.post_message(self.Submitted(value=text))
            self._input.text = ""
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
            if selected is not None and hasattr(selected, "suggestion"):
                self._apply_autocomplete(selected.suggestion)
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
        if hasattr(item, "suggestion"):
            self._apply_autocomplete(item.suggestion)
        self._dropdown.display = False

    def set_text(self, text: str, *, reopen: bool = False) -> None:
        """Replace the input contents, focus it, and move cursor to the end.

        By default the resulting Changed event is suppressed so a programmatic
        set does not re-open the dropdown. Pass reopen=True to let the dropdown
        recompute on the new value (e.g. after completing a command name, to
        reveal its sub-commands/args). Suppression is only armed when the value
        actually changes; an unchanged value fires no Changed event and would
        otherwise leave the flag armed, swallowing the next real keystroke.
        """
        self._suppress_dropdown = text != self._input.text and not reopen
        self._input.text = text
        self._input.focus()
        self._input.move_cursor(self._input.document.end)

    def _apply_autocomplete(self, suggestion: Suggestion) -> None:
        """Insert the completed text and move cursor to the end."""
        self.set_text(suggestion.insert_text, reopen=suggestion.reopen)

    def _update_dropdown(self, text: str) -> None:
        body = text[1:]
        if " " in body:
            suggestions = self._arg_suggestions(body)
        else:
            suggestions = self._command_suggestions(body.lower())
        if not suggestions:
            self._dropdown.display = False
            return

        self._dropdown.clear()
        for suggestion in suggestions:
            item = ListItem(Static(suggestion.label, markup=True))
            item.suggestion = suggestion  # type: ignore[attr-defined]
            self._dropdown.append(item)
        self._dropdown.index = None
        self._dropdown.display = True

    def _command_suggestions(self, prefix: str) -> list[Suggestion]:
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
        return [
            Suggestion(
                label=f"[b]/{cmd.name}[/b] — {cmd.description} [dim]({cmd.category})[/dim]",
                insert_text=f"/{cmd.name} ",
                reopen=bool(cmd.arg_completer or cmd.modes),
            )
            for cmd in prefix_matches + substr_matches
        ]

    def _arg_suggestions(self, body: str) -> list[Suggestion]:
        """Complete command arguments: first-arg values and trailing mode words."""
        name, _, rest = body.partition(" ")
        cmd = find_command(name.lower())
        if cmd is None:
            return []
        # First-argument value completion (e.g. /theme <name>, /workflow <name>).
        if cmd.arg_completer is not None and " " not in rest:
            partial = rest.lower()
            values = cmd.arg_completer()
            matches = [v for v in values if v.startswith(partial)] + [
                v for v in values if partial in v and not v.startswith(partial)
            ]
            return [
                Suggestion(
                    label=f"[b]{value}[/b]",
                    insert_text=f"/{cmd.name} {value} ",
                    reopen=bool(cmd.modes),
                )
                for value in matches
            ]
        # Trailing mode-word completion (e.g. /stock AAPL quick). The mode is the
        # last token; everything before it is positional. Modes appear once enough
        # positional args are present (mode_min_args) — so `/market ` shows them
        # immediately while `/stock ` waits for a symbol. A bare trailing space
        # lists all modes so they are discoverable without memorizing them;
        # applying one does not re-open the menu (see the _suppress_dropdown guard
        # in on_text_area_changed).
        if cmd.modes:
            tokens = rest.split()
            if rest.endswith(" ") or not rest:
                partial, positional = "", tokens
            else:
                partial, positional = tokens[-1].lower(), tokens[:-1]
            if len(positional) >= cmd.mode_min_args:
                head = body[: len(body) - len(partial)]
                return [
                    Suggestion(
                        label=f"[b]{mode}[/b] [dim](mode)[/dim]",
                        insert_text=f"/{head}{mode} ",
                    )
                    for mode in cmd.modes
                    if mode.startswith(partial)
                ]
        return []

    def _autocomplete(self) -> None:
        if not self._dropdown.display:
            return
        selected = self._dropdown.highlighted_child
        if selected and hasattr(selected, "suggestion"):
            self._apply_autocomplete(selected.suggestion)
            self._dropdown.display = False
        elif self._dropdown.children:
            first = self._dropdown.children[0]
            if hasattr(first, "suggestion"):
                self._apply_autocomplete(first.suggestion)
                self._dropdown.display = False

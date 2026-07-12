from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from quantagent.tui.commands import commands_by_category


class HelpScreen(ModalScreen[None]):
    """Modal reference of slash commands (grouped by category) and key bindings."""

    BINDINGS = [
        Binding("escape", "dismiss_help", "Close"),
        Binding("q", "dismiss_help", "Close", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog") as dialog:
            dialog.border_title = "Help"
            with VerticalScroll(id="help-body"):
                for category, commands in commands_by_category().items():
                    yield Static(category, classes="help-category")
                    with Grid(classes="help-grid"):
                        for cmd in commands:
                            yield Static(cmd.usage, classes="help-usage")
                            yield Static(cmd.description, classes="help-description")
                yield Static("Keys", classes="help-category")
                with Grid(classes="help-grid"):
                    for key, description in self._key_hints():
                        yield Static(key, classes="help-usage")
                        yield Static(description, classes="help-description")
            yield Static("esc close  ·  scroll with arrows", classes="help-footer")

    def _key_hints(self) -> list[tuple[str, str]]:
        hints = []
        for binding in self.app.BINDINGS:
            if isinstance(binding, Binding) and binding.description:
                hints.append((binding.key, binding.description))
        hints.append(("ctrl+p", "Command palette (incl. theme picker)"))
        return hints

    def action_dismiss_help(self) -> None:
        self.dismiss()

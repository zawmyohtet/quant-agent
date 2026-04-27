from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import LoadingIndicator, Static

from quantagent.tui.session_state import SessionState


class ChatFooter(Horizontal):
    """One-line footer below chat input showing loading state and interrupt hint."""

    def __init__(self, state: SessionState, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.state = state
        self._indicator: LoadingIndicator | None = None
        self._hint: Static | None = None

    def compose(self) -> ComposeResult:
        self._indicator = LoadingIndicator(id="footer-loading")
        self._indicator.display = False
        self._hint = Static("[dim]esc interrupt[/]", id="footer-hint")
        self._hint.display = False
        yield self._indicator
        yield Static(id="footer-spacer")
        yield self._hint

    def on_mount(self) -> None:
        self.refresh_state()

    def refresh_state(self) -> None:
        """Re-render the footer from current state."""
        if self._indicator is not None and self._hint is not None:
            self._indicator.display = self.state.is_running
            self._hint.display = self.state.is_running

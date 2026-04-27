from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import LoadingIndicator, Static

from quantagent.tui.session_state import SessionState


class StatusBar(Horizontal):
    """One-line footer showing current session state and loading indicator."""

    def __init__(self, state: SessionState, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.state = state
        self._info: Static | None = None
        self._indicator: LoadingIndicator | None = None
        self._hint: Static | None = None

    def compose(self) -> ComposeResult:
        self._info = Static(id="status-info")
        self._indicator = LoadingIndicator(id="status-loading")
        self._indicator.display = False
        self._hint = Static("[dim]esc interrupt[/]", id="status-hint")
        self._hint.display = False
        yield self._info
        yield self._indicator
        yield self._hint

    def on_mount(self) -> None:
        self.refresh_state()

    def refresh_state(self) -> None:
        """Re-render the status line from current state."""
        if self._info is None:
            return
        model = self.state.config.model
        provider = self.state.config.provider
        thread = self.state.thread_id[:8] if self.state.thread_id else "none"
        tokens = f"{self.state.token_count:,}t"
        self._info.update(
            f"model: {model} | provider: {provider} | thread: #{thread} | {tokens}"
        )
        if self._indicator is not None and self._hint is not None:
            self._indicator.display = self.state.is_running
            self._hint.display = self.state.is_running

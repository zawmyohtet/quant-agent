from __future__ import annotations

from typing import Any

from textual.widgets import Static

from quantagent.tui.session_state import SessionState


class StatusBar(Static):
    """One-line footer showing current session state."""

    def __init__(self, state: SessionState, **kwargs: Any) -> None:
        kwargs.setdefault("markup", True)
        super().__init__(**kwargs)
        self.state = state

    def on_mount(self) -> None:
        self.refresh_state()

    def refresh_state(self) -> None:
        """Re-render the status line from current state."""
        model = self.state.config.model
        provider = self.state.config.provider
        thread = self.state.thread_id[:8] if self.state.thread_id else "none"
        tokens = f"{self.state.token_count:,}t"
        base = f"model: {model} | provider: {provider} | thread: #{thread} | {tokens}"
        if self.state.is_running:
            base += " | [dim blink]●[/] Running...  [dim]esc interrupt[/]"
        self.update(base)

from __future__ import annotations

import time
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from quantagent.tui.session_state import SessionState


class StatusBar(Horizontal):
    """One-line status bar: activity state on the left, session info on the right."""

    def __init__(self, state: SessionState, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.state = state
        self._activity = Static(id="status-activity")
        self._model = Static(id="status-model", classes="status-segment")
        self._provider = Static(id="status-provider", classes="status-segment")
        self._thread = Static(id="status-thread", classes="status-segment")
        self._tokens = Static(id="status-tokens", classes="status-segment")

    def compose(self) -> ComposeResult:
        yield self._activity
        yield Static(id="status-spacer")
        yield self._model
        yield self._provider
        yield self._thread
        yield self._tokens

    def on_mount(self) -> None:
        self.set_interval(1.0, self._tick)
        self.refresh_state()

    def refresh_state(self) -> None:
        """Re-render every segment from current state."""
        self._render_activity()
        self._model.update(self.state.config.model)
        self._provider.update(self.state.config.provider)
        thread = self.state.thread_id[:8] if self.state.thread_id else "none"
        self._thread.update(f"#{thread}")
        self._tokens.update(f"{self.state.token_count:,} tok")

    def _tick(self) -> None:
        if self.state.is_running:
            self._render_activity()

    def _render_activity(self) -> None:
        if not self.state.is_running:
            self._activity.update("● idle")
            self._activity.set_class(False, "-running")
            return
        activity = self.state.current_activity or "thinking"
        elapsed = ""
        if self.state.turn_started_at is not None:
            elapsed = f" {int(time.monotonic() - self.state.turn_started_at)}s"
        self._activity.update(f"◐ {activity}…{elapsed}")
        self._activity.set_class(True, "-running")

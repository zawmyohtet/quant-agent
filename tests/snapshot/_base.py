"""Shared base for snapshot-test apps."""

from __future__ import annotations

from typing import Any

from textual.app import App

# Pin snapshot baselines to the app's default theme (QuantAgentConfig.theme).
_SNAPSHOT_THEME = "nord"


class SnapshotApp(App):
    """App base that renders with the same theme as the real application."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.theme = _SNAPSHOT_THEME

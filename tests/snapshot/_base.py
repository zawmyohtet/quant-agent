"""Shared base for snapshot-test apps."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import App

# Pin snapshot baselines to the app's default theme (QuantAgentConfig.theme).
_SNAPSHOT_THEME = "nord"

_APP_TCSS = Path(__file__).parent.parent.parent / "quantagent" / "tui" / "app.tcss"


class SnapshotApp(App):
    """App base that renders with the real application's theme and stylesheet."""

    CSS_PATH = _APP_TCSS

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.theme = _SNAPSHOT_THEME

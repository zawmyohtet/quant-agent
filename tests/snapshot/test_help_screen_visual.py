"""Snapshot tests for HelpScreen visual states."""

from __future__ import annotations

from pathlib import Path

from quantagent.tui.widgets.help_screen import HelpScreen
from tests.snapshot._base import SnapshotApp

_PROJECT_ROOT = Path(__file__).parent.parent.parent


class _HelpScreenApp(SnapshotApp):
    """Minimal app showing the HelpScreen modal."""

    CSS_PATH = _PROJECT_ROOT / "quantagent" / "tui" / "app.tcss"

    def on_mount(self) -> None:
        self.push_screen(HelpScreen())


class TestHelpScreenSnapshots:
    """Visual regression tests for HelpScreen."""

    def test_default_state(self, snap_compare: object) -> None:
        assert snap_compare(_HelpScreenApp())

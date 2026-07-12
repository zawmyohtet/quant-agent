"""Snapshot tests for ThreadSelectorScreen visual states."""

from __future__ import annotations

from quantagent.tui.widgets.thread_selector import ThreadSelectorScreen
from tests.snapshot._base import SnapshotApp

_SAMPLE_THREADS = [
    {
        "id": "abc12345-def6-7890-abcd-ef1234567890",
        "created_at": "2026-04-29T10:00:00+00:00",
        "model": "openai:gpt-4o",
        "provider": "yfinance",
        "first_message_preview": "analysis AAPL",
    },
    {
        "id": "11122233-4444-5555-6666-777888999000",
        "created_at": "2026-04-28T08:00:00+00:00",
        "model": "anthropic:claude-3.5",
        "provider": "polygon",
        "first_message_preview": "backtest TSLA momentum strategy",
    },
]


class _FakeState:
    """Stand-in for SessionState providing canned threads."""

    def __init__(self, threads: list[dict]) -> None:
        self._threads = threads

    async def list_threads(self) -> list[dict]:
        return self._threads


class _ThreadSelectorEmptyApp(SnapshotApp):
    """Minimal app showing ThreadSelectorScreen with no threads."""

    def __init__(self) -> None:
        super().__init__()
        self.state = _FakeState([])

    def on_mount(self) -> None:
        self.push_screen(ThreadSelectorScreen())


class _FrozenAgeThreadSelector(ThreadSelectorScreen):
    """Thread selector with deterministic relative ages for stable snapshots."""

    @staticmethod
    def _humanize(dt: object) -> str:
        return "2d ago"


class _ThreadSelectorWithThreadsApp(SnapshotApp):
    """Minimal app showing ThreadSelectorScreen populated with sample threads."""

    def __init__(self) -> None:
        super().__init__()
        self.state = _FakeState(_SAMPLE_THREADS)

    def on_mount(self) -> None:
        self.push_screen(_FrozenAgeThreadSelector())


class TestThreadSelectorScreenSnapshots:
    """Visual regression tests for ThreadSelectorScreen."""

    def test_empty_state(self, snap_compare: object) -> None:
        assert snap_compare(_ThreadSelectorEmptyApp())

    def test_with_threads(self, snap_compare: object) -> None:
        assert snap_compare(_ThreadSelectorWithThreadsApp())

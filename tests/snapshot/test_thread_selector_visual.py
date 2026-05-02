"""Snapshot tests for ThreadSelectorScreen visual states."""
from __future__ import annotations

from textual.app import App, ComposeResult

from quantagent.tui.widgets.thread_selector import ThreadSelectorScreen


class _ThreadSelectorEmptyApp(App):
    """Minimal app showing ThreadSelectorScreen with no threads."""

    def compose(self) -> ComposeResult:
        yield ThreadSelectorScreen()


class _ThreadSelectorWithThreadsApp(App):
    """Minimal app showing ThreadSelectorScreen populated with sample threads."""

    def compose(self) -> ComposeResult:
        yield ThreadSelectorScreen()

    async def on_mount(self) -> None:
        selector = self.query_one(ThreadSelectorScreen)
        selector._threads = [
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
        list_view = selector.query_one("#thread-list")
        list_view.clear()
        from textual.widgets import ListItem, Static

        for t in selector._threads:
            label = f'#{t["id"][:8]}  "{t["first_message_preview"][:30]}"  2d ago'
            item = ListItem(Static(label))
            item.thread_id = t["id"]  # type: ignore[attr-defined]
            list_view.append(item)
        if list_view.children:
            list_view.index = 0  # type: ignore[attr-defined]


class TestThreadSelectorScreenSnapshots:
    """Visual regression tests for ThreadSelectorScreen."""

    def test_empty_state(self, snap_compare: object) -> None:
        assert snap_compare(_ThreadSelectorEmptyApp())

    def test_with_threads(self, snap_compare: object) -> None:
        assert snap_compare(_ThreadSelectorWithThreadsApp())

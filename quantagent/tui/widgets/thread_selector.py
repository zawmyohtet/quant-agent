from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import ListItem, ListView, Static

from quantagent.tui.session_state import SessionState

if TYPE_CHECKING:
    from quantagent.tui.app import QuantAgentApp

logger = logging.getLogger(__name__)


class ThreadSelectorScreen(ModalScreen):
    """Modal for browsing and switching conversation threads."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._threads: list[dict] = []
        self._delete_task: asyncio.Task[None] | None = None
        self._switch_task: asyncio.Task[None] | None = None

    async def on_mount(self) -> None:
        state: SessionState = cast("QuantAgentApp", self.app).state
        self._threads = await state.list_threads()
        list_view = self.query_one("#thread-list", ListView)
        for t in self._threads:
            preview = t.get("first_message_preview") or "(untitled)"
            created = t.get("created_at") or ""
            try:
                dt = datetime.fromisoformat(created)
                age = self._humanize(dt)
            except Exception:
                age = created
            label = f'#{t["id"][:8]}  "{preview[:30]}"  {age}'
            item = ListItem(Static(Text(label)))
            item.thread_id = t["id"]  # type: ignore[attr-defined]
            list_view.append(item)
        if list_view.children:
            list_view.index = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="thread-dialog") as dialog:
            dialog.border_title = "Conversation Threads"
            yield ListView(id="thread-list")
            yield Static(Text("enter switch  ·  del delete  ·  esc cancel"), classes="modal-muted")

    def on_key(self, event: Key) -> None:
        if event.key == "delete":
            event.stop()
            self._delete_task = asyncio.create_task(self._delete_current())
        elif event.key == "escape":
            self.dismiss()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        tid = getattr(item, "thread_id", None)
        if tid:
            self._switch_to(tid)

    def _switch_to(self, thread_id: str) -> None:
        app = cast("QuantAgentApp", self.app)
        self._switch_task = asyncio.create_task(app.switch_thread(thread_id))
        self.dismiss()

    async def _delete_current(self) -> None:
        list_view = self.query_one("#thread-list", ListView)
        item = list_view.highlighted_child
        if not item:
            return
        tid = getattr(item, "thread_id", None)
        if not tid:
            return
        app = cast("QuantAgentApp", self.app)
        if app.runner:
            await app.runner.delete_thread(tid)
        else:
            await app.state.delete_thread(tid)
        list_view.remove_children([item])
        if not list_view.children:
            self.dismiss()

    @staticmethod
    def _humanize(dt: datetime) -> str:
        now = datetime.now(UTC)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        delta = now - dt
        if delta.days > 1:
            return f"{delta.days}d ago"
        if delta.days == 1:
            return "yesterday"
        hours = delta.seconds // 3600
        if hours > 0:
            return f"{hours}h ago"
        minutes = delta.seconds // 60
        if minutes > 0:
            return f"{minutes}m ago"
        return "just now"

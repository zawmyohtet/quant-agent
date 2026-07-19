from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from rich.console import RenderableType
from rich.markdown import Markdown
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import ScrollableContainer
from textual.widgets import Static

logger = logging.getLogger(__name__)

_MAX_DOM_MESSAGES = 50

_EMPTY_STATE_ID = "empty-state"
_EMPTY_STATE_TEXT = "No messages yet — ask about a stock, or press F1 for help"


@dataclass
class _MessageEntry:
    message_id: str
    kind: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class MessageView(ScrollableContainer):
    """Scrollable message history with virtualization (max 50 DOM nodes)."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._all_entries: list[_MessageEntry] = []
        self._dom_map: dict[str, Static] = {}
        self._agent_buffer_id: str | None = None
        self._empty_state = Static(_EMPTY_STATE_TEXT, id=_EMPTY_STATE_ID)

    def compose(self) -> ComposeResult:
        yield self._empty_state

    # -- Public API ----------------------------------------------------------

    def add_user_message(self, text: str) -> None:
        entry = _MessageEntry(message_id=self._new_id(), kind="user", content=text)
        self._append_entry(entry)

    def begin_agent_message(self) -> str:
        mid = self._new_id()
        entry = _MessageEntry(message_id=mid, kind="agent", content="")
        self._append_entry(entry)
        self._agent_buffer_id = mid
        return mid

    def append_to_agent_message(self, message_id: str, chunk: str) -> None:
        entry = self._find_entry(message_id)
        if entry:
            entry.content += chunk
            self._update_dom(entry)

    def add_tool_call(self, call_id: str, tool_name: str, args: dict) -> None:
        entry = _MessageEntry(
            message_id=call_id,
            kind="tool_start",
            content=f"{tool_name} — running…",
            metadata={"tool_name": tool_name, "args": args, "result": None},
        )
        self._append_entry(entry)

    def update_tool_progress(self, call_id: str, text: str) -> None:
        """Update a running tool line with in-flight progress text.

        Falls back to the most recent running tool when the call_id is
        empty or unknown; completed tool lines are never rewritten.
        """
        entry = self._find_entry(call_id) if call_id else None
        if entry is None or entry.kind != "tool_start":
            entry = next(
                (e for e in reversed(self._all_entries) if e.kind == "tool_start"),
                None,
            )
        if entry is None:
            return
        entry.content = f"{entry.metadata['tool_name']} — {text}"
        self._update_dom(entry)

    def complete_tool_call(self, call_id: str, result: str, *, is_error: bool = False) -> None:
        entry = self._find_entry(call_id)
        if entry:
            entry.metadata["result"] = result
            entry.metadata["is_error"] = is_error
            entry.kind = "tool_done"
            status = "failed" if is_error else "done"
            entry.content = f"{entry.metadata['tool_name']} — {status}"
            self._update_dom(entry)

    def add_assistant_message(self, text: str) -> None:
        """Append a complete assistant message rendered as Markdown.

        Unlike ``begin_agent_message``, this is a one-shot entry for
        deterministic (non-streamed) output and does not touch the streaming
        buffer id.
        """
        entry = _MessageEntry(message_id=self._new_id(), kind="agent", content=text)
        self._append_entry(entry)

    def add_system_message(self, text: str) -> None:
        entry = _MessageEntry(message_id=self._new_id(), kind="system", content=text)
        self._append_entry(entry)

    def add_error_message(self, text: str, retryable: bool = False) -> None:
        entry = _MessageEntry(
            message_id=self._new_id(),
            kind="error",
            content=text,
            metadata={"retryable": retryable},
        )
        self._append_entry(entry)

    def clear(self) -> None:
        self._all_entries.clear()
        self._agent_buffer_id = None
        for widget in self._dom_map.values():
            widget.remove()
        self._dom_map.clear()
        self._empty_state.display = True

    def last_user_message(self) -> str | None:
        for entry in reversed(self._all_entries):
            if entry.kind == "user":
                return entry.content
        return None

    def export_markdown(self) -> str:
        lines: list[str] = []
        for entry in self._all_entries:
            if entry.kind == "user":
                lines.append(f"**You:** {entry.content}\n")
            elif entry.kind == "agent":
                lines.append(f"**Agent:** {entry.content}\n")
            elif entry.kind == "system":
                lines.append(f"*{entry.content}*\n")
            elif entry.kind == "error":
                lines.append(f"**Error:** {entry.content}\n")
            elif entry.kind in ("tool_start", "tool_done"):
                tool = entry.metadata.get("tool_name", "tool")
                lines.append(f"`{tool}` → {entry.metadata.get('result', '…')}\n")
        return "\n".join(lines)

    # -- Internals -----------------------------------------------------------

    def _new_id(self) -> str:
        from uuid import uuid4

        return str(uuid4())

    def _find_entry(self, mid: str) -> _MessageEntry | None:
        for e in self._all_entries:
            if e.message_id == mid:
                return e
        return None

    def _append_entry(self, entry: _MessageEntry) -> None:
        self._empty_state.display = False
        self._all_entries.append(entry)
        widget = self._render_entry(entry)
        self._dom_map[entry.message_id] = widget
        self.mount(widget)
        self._enforce_limit()
        self.scroll_end(animate=False)

    def _remove_entry(self, mid: str) -> None:
        entry = self._find_entry(mid)
        if entry:
            self._all_entries.remove(entry)
        widget = self._dom_map.pop(mid, None)
        if widget:
            widget.remove()

    def _enforce_limit(self) -> None:
        message_widgets = [c for c in self.children if c.id != _EMPTY_STATE_ID]
        while len(message_widgets) > _MAX_DOM_MESSAGES:
            oldest = message_widgets.pop(0)
            for mid, w in self._dom_map.items():
                if w is oldest:
                    del self._dom_map[mid]
                    break
            oldest.remove()

    def _update_dom(self, entry: _MessageEntry) -> None:
        widget = self._dom_map.get(entry.message_id)
        if widget:
            widget.update(self._to_renderable(entry))
            self.scroll_end(animate=False)

    def _render_entry(self, entry: _MessageEntry) -> Static:
        return Static(self._to_renderable(entry), classes=f"msg-{entry.kind}")

    def _to_renderable(self, entry: _MessageEntry) -> RenderableType:
        # Dynamic content (user input, tool output, exception text) is assembled
        # as plain Text so stray "[...]" sequences never parse as Rich markup.
        if entry.kind == "user":
            return Text.assemble(("You", "bold cyan"), "\n", entry.content)
        if entry.kind == "agent":
            return Markdown(entry.content)
        if entry.kind == "system":
            return Text(entry.content, style="dim italic")
        if entry.kind == "error":
            text = Text.assemble(("Error: ", "bold red"), entry.content)
            if entry.metadata.get("retryable"):
                text.append("\nType /retry to retry", style="dim")
            return text
        if entry.kind == "tool_start":
            return Text.assemble(("● ", "dim"), (entry.content, "dim"))
        if entry.kind == "tool_done":
            if entry.metadata.get("is_error"):
                return Text.assemble(("✗ ", "bold red"), (entry.content, "dim"))
            return Text.assemble(("✓ ", "green"), (entry.content, "dim"))
        return Text(entry.content)

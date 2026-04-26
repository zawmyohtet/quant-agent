from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from rich.console import RenderableType
from rich.markdown import Markdown
from rich.text import Text
from textual.containers import ScrollableContainer
from textual.widgets import Static

logger = logging.getLogger(__name__)

_MAX_DOM_MESSAGES = 50


@dataclass
class _MessageEntry:
    message_id: str
    kind: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)


class MessageView(ScrollableContainer):
    """Scrollable message history with virtualization (max 50 DOM nodes)."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._all_entries: list[_MessageEntry] = []
        self._dom_map: dict[str, Static] = {}
        self._agent_buffer_id: str | None = None
        self._thinking_id: str | None = None

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
        summary = ", ".join(f'{k}="{v}"' for k, v in args.items())
        entry = _MessageEntry(
            message_id=call_id,
            kind="tool_start",
            content=f"─ {tool_name}({summary})…",
            metadata={"tool_name": tool_name, "args": args, "result": None},
        )
        self._append_entry(entry)

    def complete_tool_call(self, call_id: str, result: str) -> None:
        entry = self._find_entry(call_id)
        if entry:
            entry.metadata["result"] = result
            entry.kind = "tool_done"
            preview = result[:120].replace("\n", " ")
            entry.content = f"{entry.content.rstrip('…')} → {preview}"
            self._update_dom(entry)

    def add_system_message(self, text: str) -> None:
        entry = _MessageEntry(message_id=self._new_id(), kind="system", content=text)
        self._append_entry(entry)

    def add_error_message(self, text: str, retryable: bool = False) -> None:
        content = f"[bold red]Error:[/] {text}"
        if retryable:
            content += "\n[dim]Press r to retry[/]"
        entry = _MessageEntry(
            message_id=self._new_id(),
            kind="error",
            content=content,
            metadata={"retryable": retryable},
        )
        self._append_entry(entry)

    def show_thinking(self) -> str:
        mid = self._new_id()
        entry = _MessageEntry(message_id=mid, kind="thinking", content="● ● ●")
        self._append_entry(entry)
        self._thinking_id = mid
        return mid

    def hide_thinking(self, indicator_id: str) -> None:
        self._remove_entry(indicator_id)
        if self._thinking_id == indicator_id:
            self._thinking_id = None

    def clear(self) -> None:
        self._all_entries.clear()
        self._dom_map.clear()
        self._agent_buffer_id = None
        self._thinking_id = None
        for child in list(self.children):
            child.remove()

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
        while len(self.children) > _MAX_DOM_MESSAGES:
            oldest = self.children[0]
            for mid, w in list(self._dom_map.items()):
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
        if entry.kind == "user":
            return Text.from_markup(f"[bold cyan]You[/]\n{entry.content}")
        if entry.kind == "agent":
            return Markdown(entry.content)
        if entry.kind == "system":
            return Text.from_markup(f"[dim italic]{entry.content}[/]")
        if entry.kind == "error":
            return Text.from_markup(entry.content)
        if entry.kind in ("tool_start", "tool_done"):
            return Text.from_markup(f"[dim]{entry.content}[/]")
        if entry.kind == "thinking":
            return Text.from_markup(f"[dim]{entry.content}[/]")
        return Text(entry.content)

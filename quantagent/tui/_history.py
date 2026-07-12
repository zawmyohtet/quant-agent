"""Replay persisted LangGraph messages into the MessageView.

Used when switching threads: the checkpointer holds the full message history
for a thread_id, and this module renders those messages back into the UI so a
switched-to conversation looks the way it did when it was live.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from quantagent.tui.widgets.message_view import MessageView


def _text_of(content: Any) -> str:
    """Extract plain text from a message's content (str or block list)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "".join(parts)
    return str(content) if content else ""


def _tool_results(messages: list[Any]) -> dict[str, tuple[str, bool]]:
    """Map tool_call_id -> (result text, is_error) from ToolMessages."""
    results: dict[str, tuple[str, bool]] = {}
    for msg in messages:
        if getattr(msg, "type", None) != "tool":
            continue
        call_id = getattr(msg, "tool_call_id", None)
        if not call_id:
            continue
        is_error = getattr(msg, "status", None) == "error"
        results[call_id] = (_text_of(getattr(msg, "content", "")), is_error)
    return results


def replay_messages(messages: list[Any], view: MessageView) -> None:
    """Render a thread's checkpointed messages into ``view`` in order."""
    results = _tool_results(messages)

    for msg in messages:
        kind = getattr(msg, "type", None)
        if kind == "human":
            view.add_user_message(_text_of(getattr(msg, "content", "")))
        elif kind == "ai":
            text = _text_of(getattr(msg, "content", ""))
            if text.strip():
                mid = view.begin_agent_message()
                view.append_to_agent_message(mid, text)
            for call in getattr(msg, "tool_calls", None) or []:
                call_id = call.get("id") or ""
                view.add_tool_call(call_id, call.get("name", "tool"), call.get("args", {}))
                if call_id in results:
                    result, is_error = results[call_id]
                    view.complete_tool_call(call_id, result, is_error=is_error)
        # system and tool messages are not rendered as standalone lines.

    view._agent_buffer_id = None

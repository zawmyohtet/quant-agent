"""Tool-progress middleware — tags in-tool progress with the call id.

Long-running tools report progress via
``quantagent.utils.progress.report_progress``. This middleware binds the
active tool-call id around each tool invocation so those reports can be
routed to the correct tool line in the TUI.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from langchain.agents.middleware.types import AgentMiddleware
from langchain.messages import ToolMessage
from langchain.tools.tool_node import ToolCallRequest
from langgraph.types import Command

from quantagent.utils.progress import bind_call_id


class ToolProgressMiddleware(AgentMiddleware):
    """Binds the current tool-call id for the progress channel."""

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """Wrap sync tool execution with the call-id binding."""
        with bind_call_id(request.tool_call.get("id") or ""):
            return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        """Wrap async tool execution with the call-id binding."""
        with bind_call_id(request.tool_call.get("id") or ""):
            return await handler(request)

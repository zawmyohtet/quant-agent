"""Error-logging middleware — logs tool failures with full stack traces."""
from __future__ import annotations

import logging
from collections.abc import Callable

from langchain.agents.middleware.types import AgentMiddleware
from langchain.messages import ToolMessage
from langchain.tools.tool_node import ToolCallRequest
from langgraph.types import Command

logger = logging.getLogger(__name__)


class ErrorLoggingMiddleware(AgentMiddleware):
    """Logs every tool call failure with a full stack trace to the logging system.

    The file handler installed by ``quantagent.utils.logging.init_file_logging()``
    captures these records and writes them to ``~/.quantagent/logs/errors.log``.

    The original error string is still returned to the LLM as a ToolMessage so the
    agent can handle the failure gracefully.
    """

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """Wrap tool execution — log errors, return error message to LLM."""
        try:
            return handler(request)
        except Exception as exc:
            tool_name = request.tool_call["name"]
            tool_args = request.tool_call.get("args", {})
            logger.error(
                "Tool '%s' failed.  args=%s  error=%s: %s",
                tool_name,
                tool_args,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            return ToolMessage(
                content=f"Error in {tool_name}: {exc}",
                tool_call_id=request.tool_call["id"],
            )

"""Error-logging middleware — logs tool failures with full stack traces."""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from langchain.agents.middleware.types import AgentMiddleware
from langchain.messages import ToolMessage
from langchain.tools.tool_node import ToolCallRequest
from langgraph.types import Command

logger = logging.getLogger(__name__)


class ErrorLoggingMiddleware(AgentMiddleware):
    """Logs every tool call failure to the logging system.

    ToolNode swallows most exceptions and converts them to error ToolMessages
    before they reach this middleware. Therefore we inspect the ToolMessage
    result for ``status == "error"`` in addition to catching any exceptions
    that do propagate.

    The file handler installed by ``quantagent.utils.logging.init_file_logging()``
    captures these records and writes them to ``~/.quantagent/logs/errors.log``.
    """

    @staticmethod
    def _is_error_result(result: ToolMessage | Command) -> bool:
        """Return True if the result indicates a tool failure."""
        if isinstance(result, ToolMessage):
            return getattr(result, "status", None) == "error"
        return False

    def _log_and_return(
        self, request: ToolCallRequest, result: ToolMessage | Command
    ) -> ToolMessage | Command:
        """Log error ToolMessages and return the result unchanged."""
        if self._is_error_result(result):
            tool_name = request.tool_call["name"]
            tool_args = request.tool_call.get("args", {})
            content = result.content if isinstance(result, ToolMessage) else str(result)
            logger.error(
                "Tool '%s' failed.  args=%s  error=%s",
                tool_name,
                tool_args,
                content,
            )
        return result

    def _handle_tool_error(
        self, request: ToolCallRequest, exc: Exception
    ) -> ToolMessage | Command:
        """Log the error and return a ToolMessage for the LLM."""
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

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """Wrap tool execution — log errors, return error message to LLM."""
        try:
            result = handler(request)
        except Exception as exc:
            return self._handle_tool_error(request, exc)
        return self._log_and_return(request, result)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        """Async wrap tool execution — log errors, return error message to LLM."""
        try:
            result = await handler(request)
        except Exception as exc:
            return self._handle_tool_error(request, exc)
        return self._log_and_return(request, result)

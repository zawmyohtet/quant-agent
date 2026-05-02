"""Tests for ErrorLoggingMiddleware."""
from __future__ import annotations

import logging
from collections.abc import Callable

from langchain.messages import ToolMessage
from langchain.tools.tool_node import ToolCallRequest
from langgraph.types import Command

from quantagent.agent.middleware.error_logging import ErrorLoggingMiddleware


def _make_request(name: str, args: dict | None = None) -> ToolCallRequest:
    """Build a minimal ToolCallRequest for testing."""
    return ToolCallRequest(
        tool_call={"name": name, "args": args or {}, "id": f"call-{name}", "type": "tool_call"},
        tool=None,
        state={},
        runtime=None,  # type: ignore[arg-type]
    )


def _make_handler(return_value: ToolMessage | Command) -> Callable:
    def _handler(request: ToolCallRequest) -> ToolMessage | Command:
        return return_value

    return _handler


def _make_failing_handler(exc: Exception) -> Callable:
    def _handler(request: ToolCallRequest) -> ToolMessage | Command:
        raise exc

    return _handler


def test_wrap_tool_call_success(caplog):
    """Successful tool calls pass through untouched."""
    middleware = ErrorLoggingMiddleware()
    expected = ToolMessage(content="ok", tool_call_id="call-get_quote")
    handler = _make_handler(expected)

    with caplog.at_level(logging.ERROR):
        result = middleware.wrap_tool_call(_make_request("get_quote"), handler)

    assert result is expected
    assert caplog.record_tuples == []  # no errors logged


def test_wrap_tool_call_logs_error_and_returns_message(caplog):
    """Exception is logged with traceback and converted to a ToolMessage."""
    middleware = ErrorLoggingMiddleware()
    handler = _make_failing_handler(ValueError("bad symbol"))

    with caplog.at_level(logging.ERROR):
        result = middleware.wrap_tool_call(
            _make_request("get_quote", {"symbol": "INVALID"}), handler
        )

    assert isinstance(result, ToolMessage)
    assert "Error in get_quote" in result.content
    assert "bad symbol" in result.content
    assert result.tool_call_id == "call-get_quote"

    # One error log with the tool name and args
    assert len(caplog.records) >= 1
    record_text = caplog.records[0].getMessage()
    assert "get_quote" in record_text
    assert "INVALID" in record_text
    assert "ValueError" in record_text


def test_wrap_tool_call_logs_runtime_error(caplog):
    """RuntimeError is also logged."""
    middleware = ErrorLoggingMiddleware()
    handler = _make_failing_handler(RuntimeError("timeout"))

    with caplog.at_level(logging.ERROR):
        result = middleware.wrap_tool_call(_make_request("optimize_portfolio_tool"), handler)

    assert isinstance(result, ToolMessage)
    assert "optimize_portfolio_tool" in result.content
    assert any("RuntimeError" in r.getMessage() for r in caplog.records)


def test_wrap_tool_call_empty_args(caplog):
    """Tool call with no args is handled gracefully."""
    middleware = ErrorLoggingMiddleware()
    handler = _make_failing_handler(ConnectionError("network down"))

    result = middleware.wrap_tool_call(_make_request("search_stock_symbols", {}), handler)

    assert isinstance(result, ToolMessage)
    assert "search_stock_symbols" in result.content


def _make_async_handler(return_value: ToolMessage | Command) -> Callable:
    async def _handler(request: ToolCallRequest) -> ToolMessage | Command:
        return return_value

    return _handler


def _make_async_failing_handler(exc: Exception) -> Callable:
    async def _handler(request: ToolCallRequest) -> ToolMessage | Command:
        raise exc

    return _handler


async def test_awrap_tool_call_success(caplog):
    """Successful async tool calls pass through untouched."""
    middleware = ErrorLoggingMiddleware()
    expected = ToolMessage(content="ok", tool_call_id="call-get_quote")
    handler = _make_async_handler(expected)

    with caplog.at_level(logging.ERROR):
        result = await middleware.awrap_tool_call(_make_request("get_quote"), handler)

    assert result is expected
    assert caplog.record_tuples == []  # no errors logged


async def test_awrap_tool_call_logs_error_and_returns_message(caplog):
    """Async exception is logged with traceback and converted to a ToolMessage."""
    middleware = ErrorLoggingMiddleware()
    handler = _make_async_failing_handler(ValueError("bad symbol"))

    with caplog.at_level(logging.ERROR):
        result = await middleware.awrap_tool_call(
            _make_request("get_quote", {"symbol": "INVALID"}), handler
        )

    assert isinstance(result, ToolMessage)
    assert "Error in get_quote" in result.content
    assert "bad symbol" in result.content
    assert result.tool_call_id == "call-get_quote"

    # One error log with the tool name and args
    assert len(caplog.records) >= 1
    record_text = caplog.records[0].getMessage()
    assert "get_quote" in record_text
    assert "INVALID" in record_text
    assert "ValueError" in record_text


async def test_awrap_tool_call_logs_runtime_error(caplog):
    """Async RuntimeError is also logged."""
    middleware = ErrorLoggingMiddleware()
    handler = _make_async_failing_handler(RuntimeError("timeout"))

    with caplog.at_level(logging.ERROR):
        result = await middleware.awrap_tool_call(
            _make_request("optimize_portfolio_tool"), handler
        )

    assert isinstance(result, ToolMessage)
    assert "optimize_portfolio_tool" in result.content
    assert any("RuntimeError" in r.getMessage() for r in caplog.records)


async def test_awrap_tool_call_empty_args(caplog):
    """Async tool call with no args is handled gracefully."""
    middleware = ErrorLoggingMiddleware()
    handler = _make_async_failing_handler(ConnectionError("network down"))

    result = await middleware.awrap_tool_call(
        _make_request("search_stock_symbols", {}), handler
    )

    assert isinstance(result, ToolMessage)
    assert "search_stock_symbols" in result.content

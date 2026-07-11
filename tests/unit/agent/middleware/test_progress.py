"""Tests for ToolProgressMiddleware."""
from __future__ import annotations

from langchain.messages import ToolMessage
from langchain.tools.tool_node import ToolCallRequest

from quantagent.agent.middleware.progress import ToolProgressMiddleware
from quantagent.utils.progress import report_progress, set_progress_sink


def _make_request(call_id: str) -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"name": "slow_tool", "args": {}, "id": call_id, "type": "tool_call"},
        tool=None,
        state={},
        runtime=None,  # type: ignore[arg-type]
    )


def test_wrap_tool_call_binds_call_id() -> None:
    received: list[tuple[str, str]] = []
    set_progress_sink(lambda call_id, text: received.append((call_id, text)))
    middleware = ToolProgressMiddleware()

    def _handler(request: ToolCallRequest) -> ToolMessage:
        report_progress("working")
        return ToolMessage(content="ok", tool_call_id=request.tool_call["id"])

    result = middleware.wrap_tool_call(_make_request("call-abc"), _handler)
    set_progress_sink(None)
    assert isinstance(result, ToolMessage)
    assert received == [("call-abc", "working")]


async def test_awrap_tool_call_binds_call_id() -> None:
    received: list[tuple[str, str]] = []
    set_progress_sink(lambda call_id, text: received.append((call_id, text)))
    middleware = ToolProgressMiddleware()

    async def _handler(request: ToolCallRequest) -> ToolMessage:
        report_progress("async working")
        return ToolMessage(content="ok", tool_call_id=request.tool_call["id"])

    result = await middleware.awrap_tool_call(_make_request("call-xyz"), _handler)
    set_progress_sink(None)
    assert isinstance(result, ToolMessage)
    assert received == [("call-xyz", "async working")]


async def test_missing_call_id_binds_empty() -> None:
    received: list[str] = []
    set_progress_sink(lambda call_id, text: received.append(call_id))
    middleware = ToolProgressMiddleware()
    request = ToolCallRequest(
        tool_call={"name": "t", "args": {}, "id": None, "type": "tool_call"},
        tool=None,
        state={},
        runtime=None,  # type: ignore[arg-type]
    )

    async def _handler(req: ToolCallRequest) -> ToolMessage:
        report_progress("x")
        return ToolMessage(content="ok", tool_call_id="t")

    await middleware.awrap_tool_call(request, _handler)
    set_progress_sink(None)
    assert received == [""]

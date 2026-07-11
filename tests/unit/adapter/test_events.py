from __future__ import annotations

from quantagent.adapter.events import (
    AgentError,
    AgentEvent,
    AgentTextChunk,
    AgentTurnComplete,
    ApprovalRequest,
    SystemNotification,
    ToolCallCompleted,
    ToolCallStarted,
    ToolProgress,
)


class TestAgentEvents:
    def test_agent_text_chunk(self) -> None:
        e = AgentTextChunk(chunk="hello")
        assert e.chunk == "hello"
        assert isinstance(e, AgentEvent)

    def test_agent_turn_complete(self) -> None:
        e = AgentTurnComplete()
        assert isinstance(e, AgentEvent)

    def test_tool_call_started(self) -> None:
        e = ToolCallStarted(call_id="c1", tool_name="foo", args={"x": 1})
        assert e.tool_name == "foo"
        assert isinstance(e, AgentEvent)

    def test_tool_call_completed(self) -> None:
        e = ToolCallCompleted(call_id="c1", result="done")
        assert e.result == "done"
        assert isinstance(e, AgentEvent)

    def test_agent_error(self) -> None:
        e = AgentError(message="oops", retryable=True)
        assert e.message == "oops"
        assert e.retryable is True
        assert isinstance(e, AgentEvent)

    def test_system_notification(self) -> None:
        e = SystemNotification(text="hello")
        assert e.text == "hello"
        assert isinstance(e, AgentEvent)

    def test_approval_request(self) -> None:
        e = ApprovalRequest(call_id="c1", tool_name="bar", args={})
        assert e.tool_name == "bar"
        assert isinstance(e, AgentEvent)

    def test_tool_progress(self) -> None:
        e = ToolProgress(call_id="c1", text="step 2/4: sectors")
        assert e.call_id == "c1"
        assert e.text == "step 2/4: sectors"
        assert isinstance(e, AgentEvent)




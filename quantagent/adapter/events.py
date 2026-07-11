from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AgentEvent:
    """Base class for all agent-to-TUI events."""

    pass


@dataclass
class AgentTextChunk(AgentEvent):
    """A streamed token from the agent."""

    chunk: str


@dataclass
class AgentTurnComplete(AgentEvent):
    """Signals that the agent has finished processing a turn."""

    pass


@dataclass
class ToolCallStarted(AgentEvent):
    """Emitted when the agent invokes a tool."""

    call_id: str
    tool_name: str
    args: dict[str, Any]


@dataclass
class ToolCallCompleted(AgentEvent):
    """Emitted when a tool call finishes."""

    call_id: str
    result: str
    is_error: bool = False


@dataclass
class ToolProgress(AgentEvent):
    """Live progress from inside a running tool call.

    ``call_id`` matches the ToolCallStarted event of the running tool;
    an empty call_id means "the most recent running tool".
    """

    call_id: str
    text: str


@dataclass
class AgentError(AgentEvent):
    """Emitted when the agent encounters an error."""

    message: str
    retryable: bool = False


@dataclass
class SystemNotification(AgentEvent):
    """A system-level message for the TUI."""

    text: str


@dataclass
class ApprovalRequest(AgentEvent):
    """Request human approval before running a tool."""

    call_id: str
    tool_name: str
    args: dict[str, Any]


@dataclass
class ApprovalDecision:
    """TUI → Runner decision for a pending approval request.

    This is NOT an AgentEvent — it travels in the opposite direction
    (from TUI to the runner's approval future).
    """

    approved: bool

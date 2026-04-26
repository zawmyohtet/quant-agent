"""Approval middleware — HITL interrupt for sensitive tools."""
from __future__ import annotations

from typing import Any

from langchain.agents.middleware.human_in_the_loop import HumanInTheLoopMiddleware


class ApprovalMiddleware(HumanInTheLoopMiddleware):
    """Interrupts the agent to request human approval for sensitive tools."""

    def __init__(
        self, tools_requiring_approval: list[str], approval_callback: Any = None
    ) -> None:
        """Initialize with list of tool names that require approval."""
        interrupt_on: dict[str, Any] = dict.fromkeys(tools_requiring_approval, True)
        super().__init__(interrupt_on=interrupt_on)
        self.approval_callback = approval_callback

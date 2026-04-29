"""Interrupt processing utilities for AgentRunner.

Extracts HITL interrupt handling from AgentRunner to keep cognitive
complexity low.
"""
from __future__ import annotations

from typing import Any, Protocol


class _ApprovalRequester(Protocol):
    """Protocol for async approval requests."""

    async def __call__(self, tool_name: str, args: dict[str, Any]) -> bool:
        ...


class _InterruptResult:
    """Value object representing the outcome of a single interrupt."""

    def __init__(self, payload: Any, was_approved: bool) -> None:
        self.payload = payload
        self.was_approved = was_approved


async def _process_single_interrupt(
    value: dict[str, Any], request_approval: _ApprovalRequester
) -> _InterruptResult:
    """Handle a simple interrupt with a single action.

    Returns the resume payload and whether it was approved.
    """
    tool_name = value.get("tool_name", value.get("name", "unknown"))
    args = {
        k: v for k, v in value.items() if k not in ("tool_name", "name")
    }
    approved = await request_approval(tool_name, args)
    payload = [{"type": "approve" if approved else "reject"}]
    return _InterruptResult(payload=payload, was_approved=approved)


async def _process_action_requests(
    value: dict[str, Any], request_approval: _ApprovalRequester
) -> _InterruptResult:
    """Handle an interrupt containing multiple action_requests.

    Returns the resume payload and whether any action was approved.
    """
    from langchain.agents.middleware.human_in_the_loop import (
        ApproveDecision,
        RejectDecision,
    )

    action_requests = value.get("action_requests", [])
    decisions: list[Any] = []
    any_approved = False

    for ar in action_requests:
        ar_name = ar.get("name", "unknown")
        ar_args = ar.get("args", {})
        approved = await request_approval(ar_name, ar_args)
        if approved:
            decisions.append(ApproveDecision(type="approve"))
            any_approved = True
        else:
            decisions.append(RejectDecision(type="reject"))

    payload = {"decisions": decisions}
    return _InterruptResult(payload=payload, was_approved=any_approved)

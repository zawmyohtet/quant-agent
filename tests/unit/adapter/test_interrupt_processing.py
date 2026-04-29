"""Tests for _interrupt_processing module."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from quantagent.adapter._interrupt_processing import (
    _InterruptResult,
    _process_action_requests,
    _process_single_interrupt,
)


class TestInterruptResult:
    def test_value_object(self) -> None:
        r = _InterruptResult(payload=[{"type": "approve"}], was_approved=True)
        assert r.payload == [{"type": "approve"}]
        assert r.was_approved is True


class TestProcessSingleInterrupt:
    @pytest.mark.asyncio
    async def test_approved(self) -> None:
        requester = AsyncMock(return_value=True)
        value = {"tool_name": "fetch", "symbol": "AAPL"}

        result = await _process_single_interrupt(value, requester)

        requester.assert_awaited_once_with("fetch", {"symbol": "AAPL"})
        assert result.was_approved is True
        assert result.payload == [{"type": "approve"}]

    @pytest.mark.asyncio
    async def test_rejected(self) -> None:
        requester = AsyncMock(return_value=False)
        value = {"name": "screener", "universe": "sp500"}

        result = await _process_single_interrupt(value, requester)

        requester.assert_awaited_once_with("screener", {"universe": "sp500"})
        assert result.was_approved is False
        assert result.payload == [{"type": "reject"}]

    @pytest.mark.asyncio
    async def test_fallback_name(self) -> None:
        requester = AsyncMock(return_value=True)
        value = {"args": {}}

        await _process_single_interrupt(value, requester)

        requester.assert_awaited_once_with("unknown", {"args": {}})


class TestProcessActionRequests:
    @pytest.mark.asyncio
    async def test_all_approved(self) -> None:
        requester = AsyncMock(return_value=True)
        value = {
            "action_requests": [
                {"name": "fetch", "args": {"sym": "AAPL"}},
                {"name": "compute", "args": {"ind": "rsi"}},
            ]
        }

        with patch(
            "langchain.agents.middleware.human_in_the_loop.ApproveDecision",
            side_effect=lambda **kw: {"type": "approve", **kw},
        ):
            result = await _process_action_requests(value, requester)

        assert result.was_approved is True
        assert result.payload == {
            "decisions": [
                {"type": "approve"},
                {"type": "approve"},
            ]
        }
        assert requester.await_count == 2

    @pytest.mark.asyncio
    async def test_all_rejected(self) -> None:
        requester = AsyncMock(return_value=False)
        value = {
            "action_requests": [
                {"name": "fetch", "args": {}},
            ]
        }

        with patch(
            "langchain.agents.middleware.human_in_the_loop.RejectDecision",
            side_effect=lambda **kw: {"type": "reject", **kw},
        ):
            result = await _process_action_requests(value, requester)

        assert result.was_approved is False
        assert result.payload == {
            "decisions": [{"type": "reject"}]
        }

    @pytest.mark.asyncio
    async def test_mixed_decisions(self) -> None:
        requester = AsyncMock(side_effect=[True, False])
        value = {
            "action_requests": [
                {"name": "a", "args": {}},
                {"name": "b", "args": {}},
            ]
        }

        def _make_approve(**kw: Any) -> dict[str, Any]:
            return {"type": "approve", **kw}

        def _make_reject(**kw: Any) -> dict[str, Any]:
            return {"type": "reject", **kw}

        with patch(
            "langchain.agents.middleware.human_in_the_loop.ApproveDecision",
            side_effect=_make_approve,
        ), patch(
            "langchain.agents.middleware.human_in_the_loop.RejectDecision",
            side_effect=_make_reject,
        ):
            result = await _process_action_requests(value, requester)

        assert result.was_approved is True
        assert result.payload == {
            "decisions": [
                {"type": "approve"},
                {"type": "reject"},
            ]
        }

    @pytest.mark.asyncio
    async def test_empty_action_requests(self) -> None:
        requester = AsyncMock(return_value=True)
        value: dict[str, Any] = {"action_requests": []}

        result = await _process_action_requests(value, requester)

        assert result.was_approved is False
        assert result.payload == {"decisions": []}
        requester.assert_not_awaited()

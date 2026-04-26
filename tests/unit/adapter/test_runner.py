"""Tests for AgentRunner — agent-TUI bridge."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from quantagent.adapter.events import (
    AgentError,
    AgentTurnComplete,
)
from quantagent.adapter.runner import AgentRunner
from quantagent.tui.config import QuantAgentConfig
from quantagent.tui.session_state import SessionState


@pytest.fixture
def state() -> SessionState:
    config = QuantAgentConfig(model="openai:gpt-4o", provider="yfinance")
    return SessionState(config=config)


@pytest.fixture
def runner(state: SessionState) -> AgentRunner:
    return AgentRunner(state)


class TestAgentRunnerInit:
    def test_runner_creates_with_state(self, state: SessionState) -> None:
        runner = AgentRunner(state)
        assert runner.state is state
        assert runner._agent is None
        assert runner._checkpointer is None

    def test_runner_has_event_queue(self, runner: AgentRunner) -> None:
        assert runner.get_event_queue() is runner._queue


class TestAgentRunnerStart:
    @pytest.mark.asyncio
    async def test_start_sets_agent_and_checkpointer(
        self, runner: AgentRunner
    ) -> None:
        mock_checkpointer = AsyncMock()
        mock_agent = MagicMock()

        with (
            patch(
                "quantagent.agent.sessions.get_checkpointer",
                return_value=mock_checkpointer,
            ),
            patch(
                "quantagent.adapter.runner.create_quant_agent",
                return_value=mock_agent,
            ),
        ):
            await runner.start()
            assert runner._checkpointer is mock_checkpointer
            assert runner._agent is mock_agent

    @pytest.mark.asyncio
    async def test_start_agent_failure_emits_error(self, runner: AgentRunner) -> None:
        mock_checkpointer = AsyncMock()

        with (
            patch(
                "quantagent.agent.sessions.get_checkpointer",
                return_value=mock_checkpointer,
            ),
            patch(
                "quantagent.adapter.runner.create_quant_agent",
                side_effect=RuntimeError("model not found"),
            ),
        ):
            await runner.start()
            assert runner._agent is None

            event = runner.get_event_queue().get_nowait()
            assert isinstance(event, AgentError)
            assert "Failed to create agent" in event.message

    @pytest.mark.asyncio
    async def test_start_checkpointer_failure_emits_error(
        self, runner: AgentRunner
    ) -> None:
        with patch(
            "quantagent.agent.sessions.get_checkpointer",
            side_effect=RuntimeError("db error"),
        ):
            await runner.start()
            event = runner.get_event_queue().get_nowait()
            assert isinstance(event, AgentError)
            assert "session storage" in event.message


class TestResolveApproval:
    @pytest.mark.asyncio
    async def test_resolve_approval(self, runner: AgentRunner) -> None:
        loop = asyncio.get_running_loop()
        runner._approval_future = loop.create_future()
        runner.resolve_approval(True)
        assert runner._approval_future is None

    def test_resolve_approval_no_pending_future(self, runner: AgentRunner) -> None:
        runner._approval_future = None
        runner.resolve_approval(True)
        assert runner._approval_future is None


class TestCancel:
    def test_cancel_with_completed_task(self, runner: AgentRunner) -> None:
        mock_task = MagicMock()
        mock_task.done.return_value = True
        runner._current_task = mock_task
        runner.cancel()
        mock_task.cancel.assert_not_called()

    def test_cancel_with_active_task(self, runner: AgentRunner) -> None:
        mock_task = MagicMock()
        mock_task.done.return_value = False
        runner._current_task = mock_task
        runner.cancel()
        mock_task.cancel.assert_called_once()


class TestRunTurn:
    @pytest.mark.asyncio
    async def test_run_turn_with_no_agent_emits_error(
        self, runner: AgentRunner
    ) -> None:
        runner._agent = None
        queue = runner.get_event_queue()

        await runner.run_turn("hello")

        got_error = False
        got_complete = False
        while not queue.empty():
            event = queue.get_nowait()
            if isinstance(event, AgentError):
                got_error = True
                assert "not initialized" in event.message
            elif isinstance(event, AgentTurnComplete):
                got_complete = True

        assert got_error, "Expected AgentError event"
        assert got_complete, "Expected AgentTurnComplete event"


class TestShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_cancels_active_task(self, runner: AgentRunner) -> None:
        mock_task = MagicMock()
        mock_task.done.return_value = False
        runner._current_task = mock_task

        await runner.shutdown()
        mock_task.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_closes_checkpointer(self, runner: AgentRunner) -> None:
        mock_checkpointer = AsyncMock()
        mock_checkpointer.close = AsyncMock()
        runner._checkpointer = mock_checkpointer

        await runner.shutdown()
        mock_checkpointer.close.assert_called_once()


class TestGetEventQueue:
    def test_returns_queue(self, runner: AgentRunner) -> None:
        queue = runner.get_event_queue()
        assert queue is runner._queue

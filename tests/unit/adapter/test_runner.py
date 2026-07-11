"""Tests for AgentRunner — agent-TUI bridge."""
from __future__ import annotations

import asyncio
from types import MethodType
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

    @pytest.mark.asyncio
    async def test_run_turn_cancellation_cancels_inner_execute(
        self, runner: AgentRunner
    ) -> None:
        runner._agent = MagicMock()

        async def track_cancel(self, user_message: str) -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                raise

        with patch.object(runner, "_execute_turn", MethodType(track_cancel, runner)):
            turn_task = asyncio.create_task(runner.run_turn("hi"))
            for _ in range(100):
                if runner._current_task is not None and not runner._current_task.done():
                    break
                await asyncio.sleep(0.001)
            else:
                pytest.fail("inner _execute_turn task did not start")

            turn_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await turn_task

        assert runner._current_task is None
        got_complete = False
        queue = runner.get_event_queue()
        while not queue.empty():
            ev = queue.get_nowait()
            if isinstance(ev, AgentTurnComplete):
                got_complete = True
        assert got_complete is True


class TestShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_cancels_active_task(self, runner: AgentRunner) -> None:
        async def hang() -> None:
            try:
                await asyncio.sleep(100.0)
            except asyncio.CancelledError:
                raise

        hang_task = asyncio.create_task(hang())
        runner._current_task = hang_task

        await runner.shutdown()

        assert hang_task.done()
        assert hang_task.cancelled()
        assert runner._current_task is None

    @pytest.mark.asyncio
    async def test_shutdown_closes_checkpointer(self, runner: AgentRunner) -> None:
        mock_checkpointer = AsyncMock()
        mock_checkpointer.close = AsyncMock()
        runner._checkpointer = mock_checkpointer

        await runner.shutdown()
        mock_checkpointer.close.assert_called_once()
        assert runner._checkpointer is None

    @pytest.mark.asyncio
    async def test_shutdown_closes_conn_when_saver_has_no_close(
        self, runner: AgentRunner
    ) -> None:
        mock_conn = AsyncMock()
        mock_conn.close = AsyncMock()

        class _SaverNoClose:
            def __init__(self, conn: AsyncMock) -> None:
                self.conn = conn

        runner._checkpointer = _SaverNoClose(mock_conn)

        await runner.shutdown()

        mock_conn.close.assert_awaited_once()
        assert runner._checkpointer is None

    @pytest.mark.asyncio
    async def test_shutdown_close_checkpointer_error(
        self, runner: AgentRunner
    ) -> None:
        mock_checkpointer = AsyncMock()
        mock_checkpointer.close = AsyncMock(
            side_effect=RuntimeError("close fail")
        )
        runner._checkpointer = mock_checkpointer

        await runner.shutdown()
        mock_checkpointer.close.assert_awaited_once()
        assert runner._checkpointer is None


class TestApplyTokenCounts:
    def test_apply_total_tokens(self, runner: AgentRunner) -> None:
        from quantagent.adapter._stream_processing import _TurnContext

        context = _TurnContext()
        context.total_tokens = 42
        runner._apply_token_counts(context)
        assert runner.state.token_count == 42

    def test_apply_input_output_tokens(self, runner: AgentRunner) -> None:
        from quantagent.adapter._stream_processing import _TurnContext

        context = _TurnContext()
        context.input_tokens = 10
        context.output_tokens = 20
        runner._apply_token_counts(context)
        assert runner.state.token_count == 30

    def test_apply_no_tokens(self, runner: AgentRunner) -> None:
        from quantagent.adapter._stream_processing import _TurnContext

        context = _TurnContext()
        runner._apply_token_counts(context)
        assert runner.state.token_count == 0


class TestHandleInterrupts:
    @pytest.mark.asyncio
    async def test_all_rejected_returns_none(self, runner: AgentRunner) -> None:
        runner._pending_interrupts = {
            "int-1": {"value": {"tool_name": "fetch", "symbol": "AAPL"}}
        }
        with patch.object(
            runner, "_request_single_approval", return_value=False
        ):
            result = await runner._handle_interrupts()

        assert result is None
        assert runner._pending_interrupts == {}

    @pytest.mark.asyncio
    async def test_some_approved_returns_command(self, runner: AgentRunner) -> None:
        runner._pending_interrupts = {
            "int-1": {"value": {"tool_name": "fetch", "symbol": "AAPL"}}
        }
        with patch.object(
            runner, "_request_single_approval", return_value=True
        ), patch("langgraph.types.Command") as mock_cmd:
            await runner._handle_interrupts()

        mock_cmd.assert_called_once_with(resume={"int-1": [{"type": "approve"}]})
        assert runner._pending_interrupts == {}


class TestRequestSingleApproval:
    @pytest.mark.asyncio
    async def test_request_emits_approval_request(self, runner: AgentRunner) -> None:
        async def _resolve_later() -> None:
            await asyncio.sleep(0.01)
            runner.resolve_approval(True)

        asyncio.create_task(_resolve_later())
        result = await asyncio.wait_for(
            runner._request_single_approval("fetch", {"sym": "AAPL"}),
            timeout=1.0,
        )
        assert result is True

        event = runner.get_event_queue().get_nowait()
        from quantagent.adapter.events import ApprovalRequest

        assert isinstance(event, ApprovalRequest)
        assert event.tool_name == "fetch"


class TestReloadSkills:
    @pytest.mark.asyncio
    async def test_reload_skills_success(self, runner: AgentRunner) -> None:
        mock_agent = MagicMock()
        with patch(
            "quantagent.adapter.runner.create_quant_agent",
            return_value=mock_agent,
        ):
            await runner.reload_skills()

        assert runner._agent is mock_agent
        event = runner.get_event_queue().get_nowait()
        from quantagent.adapter.events import SystemNotification

        assert isinstance(event, SystemNotification)
        assert "reloaded" in event.text

    @pytest.mark.asyncio
    async def test_reload_skills_failure(self, runner: AgentRunner) -> None:
        with patch(
            "quantagent.adapter.runner.create_quant_agent",
            side_effect=RuntimeError("boom"),
        ):
            await runner.reload_skills()

        event = runner.get_event_queue().get_nowait()
        assert isinstance(event, AgentError)
        assert "Failed to reload skills" in event.message


class TestSetModel:
    @pytest.mark.asyncio
    async def test_set_model_success(self, runner: AgentRunner) -> None:
        mock_agent = MagicMock()
        with patch(
            "quantagent.adapter.runner.create_quant_agent",
            return_value=mock_agent,
        ):
            await runner.set_model("openai:gpt-4o-mini")

        assert runner.state.config.model == "openai:gpt-4o-mini"
        assert runner._agent is mock_agent
        event = runner.get_event_queue().get_nowait()
        from quantagent.adapter.events import SystemNotification

        assert isinstance(event, SystemNotification)
        assert "gpt-4o-mini" in event.text

    @pytest.mark.asyncio
    async def test_set_model_failure(self, runner: AgentRunner) -> None:
        with patch(
            "quantagent.adapter.runner.create_quant_agent",
            side_effect=RuntimeError("boom"),
        ):
            await runner.set_model("bad-model")

        event = runner.get_event_queue().get_nowait()
        assert isinstance(event, AgentError)
        assert "Failed to change model" in event.message





class TestProgressSink:
    @pytest.mark.asyncio
    async def test_installed_sink_enqueues_tool_progress(
        self, runner: AgentRunner
    ) -> None:
        from quantagent.adapter.events import ToolProgress
        from quantagent.utils.progress import (
            bind_call_id,
            report_progress,
            set_progress_sink,
        )

        runner._install_progress_sink()
        try:
            with bind_call_id("call-1"):
                report_progress("warming cache: 100/500")
            # call_soon_threadsafe schedules onto the loop — yield once.
            await asyncio.sleep(0)
            event = runner.get_event_queue().get_nowait()
            assert isinstance(event, ToolProgress)
            assert event.call_id == "call-1"
            assert event.text == "warming cache: 100/500"
        finally:
            set_progress_sink(None)

"""Tests for QuantAgentApp wiring (loading indicator + interrupt)."""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from quantagent.adapter.events import (
    AgentError,
    AgentTextChunk,
    AgentTurnComplete,
    ToolCallStarted,
)
from quantagent.tui.app import (
    _ID_MESSAGES,
    _ID_STATUS_BAR,
    QuantAgentApp,
)
from quantagent.tui.config import QuantAgentConfig

_VALID_ID_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_-]*$")


@pytest.fixture
def app() -> QuantAgentApp:
    config = QuantAgentConfig(model="openai:gpt-4o", provider="yfinance")
    return QuantAgentApp(config)


class TestAppWiring:
    def test_compose_yields_widgets_with_valid_ids(self, app: QuantAgentApp) -> None:
        widgets = list(app.compose())
        assert len(widgets) == 4
        for widget in widgets:
            assert widget.id is not None, "Widget id must not be None"
            assert "#" not in widget.id, f"Widget id must not contain '#': {widget.id!r}"
            assert _VALID_ID_RE.match(widget.id), f"Invalid widget id: {widget.id!r}"

    @pytest.mark.asyncio
    async def test_submit_user_message_sets_running_and_refreshes_status(
        self, app: QuantAgentApp
    ) -> None:
        mock_messages = MagicMock()
        mock_status = MagicMock()
        app.state.is_running = False
        app.runner = MagicMock()
        with (
            patch.object(
                app,
                "query_one",
                side_effect=lambda selector, _: {
                    _ID_MESSAGES: mock_messages,
                    _ID_STATUS_BAR: mock_status,
                }[selector],
            ),
            patch.object(app, "run_worker") as mock_run_worker,
        ):
            await app._submit_user_message("hello")
            assert app.state.is_running is True
            assert app.state.current_activity == "thinking"
            assert app.state.turn_started_at is not None
            mock_messages.add_user_message.assert_called_once_with("hello")
            mock_status.refresh_state.assert_called_once()
            mock_run_worker.assert_called_once()

    @pytest.mark.asyncio
    async def test_submit_user_message_blocked_when_running(self, app: QuantAgentApp) -> None:
        app.state.is_running = True
        with patch.object(app, "run_worker") as mock_run_worker:
            await app._submit_user_message("hello")
            mock_run_worker.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_event_text_chunk_creates_agent_message(self, app: QuantAgentApp) -> None:
        mock_messages = MagicMock()
        mock_messages._agent_buffer_id = None
        with patch.object(app, "query_one", return_value=mock_messages):
            await app._handle_event(AgentTextChunk(chunk="hi"))
            mock_messages.begin_agent_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_event_tool_call_started(self, app: QuantAgentApp) -> None:
        mock_messages = MagicMock()
        with patch.object(app, "query_one", return_value=mock_messages):
            await app._handle_event(ToolCallStarted(call_id="c1", tool_name="foo", args={}))
            mock_messages.add_tool_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_event_agent_error(self, app: QuantAgentApp) -> None:
        mock_messages = MagicMock()
        with patch.object(app, "query_one", return_value=mock_messages):
            await app._handle_event(AgentError(message="oops", retryable=True))
            mock_messages.add_error_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_event_turn_complete_clears_running_state(
        self, app: QuantAgentApp
    ) -> None:
        mock_messages = MagicMock()
        mock_status = MagicMock()
        app.state.is_running = True
        app.state.current_activity = "thinking"
        with patch.object(
            app,
            "query_one",
            side_effect=lambda selector, _: {
                _ID_MESSAGES: mock_messages,
                _ID_STATUS_BAR: mock_status,
            }[selector],
        ):
            await app._handle_event(AgentTurnComplete())
            assert app.state.is_running is False
            assert app.state.current_activity is None
            mock_status.refresh_state.assert_called_once()

    def test_action_cancel_agent_cancels_runner(self, app: QuantAgentApp) -> None:
        mock_messages = MagicMock()
        app.runner = MagicMock()
        with patch.object(app, "query_one", return_value=mock_messages):
            app.action_cancel_agent()
            app.runner.cancel.assert_called_once()
            mock_messages.add_system_message.assert_called_once_with("Agent turn cancelled.")

    @pytest.mark.asyncio
    async def test_on_unmount_cancels_runner_before_workers(self, app: QuantAgentApp) -> None:
        mock_runner = MagicMock()
        mock_runner.shutdown = AsyncMock()
        app.runner = mock_runner
        app._event_consumer = None
        with (
            patch.object(app.workers, "cancel_all") as mock_cancel_all,
            patch.object(
                app.workers,
                "wait_for_complete",
                new_callable=AsyncMock,
            ) as mock_wait,
        ):
            mock_wait.return_value = None
            await app.on_unmount()

        mock_runner.cancel.assert_called_once()
        mock_cancel_all.assert_called_once()
        mock_wait.assert_awaited_once()
        mock_runner.shutdown.assert_awaited_once()

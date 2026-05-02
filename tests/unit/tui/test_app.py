"""Tests for QuantAgentApp wiring (loading indicator + interrupt)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from quantagent.adapter.events import (
    AgentError,
    AgentTextChunk,
    AgentTurnComplete,
    ToolCallStarted,
)
from quantagent.tui.app import (
    _ID_CHAT_FOOTER,
    _ID_MESSAGES,
    _ID_STATUS_BAR,
    QuantAgentApp,
)
from quantagent.tui.config import QuantAgentConfig


@pytest.fixture
def app() -> QuantAgentApp:
    config = QuantAgentConfig(model="openai:gpt-4o", provider="yfinance")
    return QuantAgentApp(config)


class TestAppWiring:
    @pytest.mark.asyncio
    async def test_submit_user_message_sets_running_and_refreshes_status_and_footer(
        self, app: QuantAgentApp
    ) -> None:
        mock_messages = MagicMock()
        mock_status = MagicMock()
        mock_footer = MagicMock()
        app.state.is_running = False
        app.runner = MagicMock()
        with (
            patch.object(
                app,
                "query_one",
                side_effect=lambda selector, _: {
                    _ID_MESSAGES: mock_messages,
                    _ID_STATUS_BAR: mock_status,
                    _ID_CHAT_FOOTER: mock_footer,
                }[selector],
            ),
            patch.object(app, "run_worker") as mock_run_worker,
        ):
            await app._submit_user_message("hello")
            assert app.state.is_running is True
            mock_messages.add_user_message.assert_called_once_with("hello")
            mock_status.refresh_state.assert_called_once()
            mock_footer.refresh_state.assert_called_once()
            mock_run_worker.assert_called_once()

    @pytest.mark.asyncio
    async def test_submit_user_message_blocked_when_running(
        self, app: QuantAgentApp
    ) -> None:
        app.state.is_running = True
        with patch.object(app, "run_worker") as mock_run_worker:
            await app._submit_user_message("hello")
            mock_run_worker.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_event_text_chunk_creates_agent_message(
        self, app: QuantAgentApp
    ) -> None:
        mock_messages = MagicMock()
        mock_messages._agent_buffer_id = None
        with patch.object(app, "query_one", return_value=mock_messages):
            await app._handle_event(AgentTextChunk(chunk="hi"))
            mock_messages.begin_agent_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_event_tool_call_started(
        self, app: QuantAgentApp
    ) -> None:
        mock_messages = MagicMock()
        with patch.object(app, "query_one", return_value=mock_messages):
            await app._handle_event(
                ToolCallStarted(call_id="c1", tool_name="foo", args={})
            )
            mock_messages.add_tool_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_event_agent_error(
        self, app: QuantAgentApp
    ) -> None:
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
        mock_footer = MagicMock()
        app.state.is_running = True
        with patch.object(
            app,
            "query_one",
            side_effect=lambda selector, _: {
                _ID_MESSAGES: mock_messages,
                _ID_STATUS_BAR: mock_status,
                _ID_CHAT_FOOTER: mock_footer,
            }[selector],
        ):
            await app._handle_event(AgentTurnComplete())
            assert app.state.is_running is False
            mock_status.refresh_state.assert_called_once()
            mock_footer.refresh_state.assert_called_once()

    def test_action_cancel_agent_cancels_runner(self, app: QuantAgentApp) -> None:
        mock_messages = MagicMock()
        app.runner = MagicMock()
        with patch.object(app, "query_one", return_value=mock_messages):
            app.action_cancel_agent()
            app.runner.cancel.assert_called_once()
            mock_messages.add_system_message.assert_called_once_with(
                "Agent turn cancelled."
            )

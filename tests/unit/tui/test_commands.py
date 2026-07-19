from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from quantagent.tui.app import QuantAgentApp
from quantagent.tui.commands import (
    REGISTRY,
    _handle_analyze,
    _handle_backtest,
    _handle_compare,
    _handle_report,
    _handle_retry,
    _handle_screen,
    _handle_universe,
    _handle_warm,
    _handle_workflow,
    find_command,
)
from quantagent.tui.config import QuantAgentConfig


@pytest.fixture
def app() -> QuantAgentApp:
    config = QuantAgentConfig(model="openai:gpt-4o", provider="yfinance")
    return QuantAgentApp(config)


class TestSlashCommands:
    def test_all_commands_have_unique_names(self) -> None:
        names = [cmd.name for cmd in REGISTRY]
        assert len(names) == len(set(names))

    def test_find_command_existing(self) -> None:
        cmd = find_command("help")
        assert cmd is not None
        assert cmd.name == "help"

    def test_find_command_missing(self) -> None:
        assert find_command("nonexistent") is None

    def test_removed_list_commands_are_aliases(self) -> None:
        # /workflows and /universes are gone as standalone commands; the old
        # names now resolve to the picker-opening action commands.
        assert find_command("workflows") is find_command("workflow")
        assert find_command("universes") is find_command("universe")


class TestPickerCommands:
    """Bare invocation opens a picker; args submit a prompt directly."""

    @pytest.mark.asyncio
    async def test_workflow_with_args_submits_prompt(self, app: QuantAgentApp) -> None:
        app.runner = MagicMock()
        with patch.object(app, "_submit_user_message") as mock_submit:
            await _handle_workflow(["stock_research", "AAPL"], app)
            mock_submit.assert_called_once_with(
                "Run the 'stock_research' workflow with target AAPL "
                "and walk me through the results."
            )

    @pytest.mark.asyncio
    async def test_workflow_bare_opens_picker(self, app: QuantAgentApp) -> None:
        with patch.object(app, "push_screen") as mock_push:
            await _handle_workflow([], app)
            mock_push.assert_called_once()

    @pytest.mark.asyncio
    async def test_report_bare_opens_picker(self, app: QuantAgentApp) -> None:
        with patch.object(app, "push_screen") as mock_push:
            await _handle_report([], app)
            mock_push.assert_called_once()

    @pytest.mark.asyncio
    async def test_universe_bare_opens_picker(self, app: QuantAgentApp) -> None:
        with patch.object(app, "push_screen") as mock_push:
            await _handle_universe([], app)
            mock_push.assert_called_once()

    @pytest.mark.asyncio
    async def test_picker_no_target_selection_submits(self, app: QuantAgentApp) -> None:
        with patch.object(app, "push_screen") as mock_push:
            await _handle_workflow([], app)
        picker = mock_push.call_args.args[0]
        item = next(i for i in picker._items if not i.needs_target)
        with (
            patch.object(app, "run_worker") as mock_worker,
            patch.object(app, "_submit_user_message", MagicMock()) as mock_submit,
            patch.object(app, "prefill_input") as mock_prefill,
        ):
            picker._on_select(item)
            mock_prefill.assert_not_called()
            mock_submit.assert_called_once()
            mock_worker.assert_called_once()

    @pytest.mark.asyncio
    async def test_picker_target_selection_prefills(self, app: QuantAgentApp) -> None:
        with patch.object(app, "push_screen") as mock_push:
            await _handle_workflow([], app)
        picker = mock_push.call_args.args[0]
        item = next(i for i in picker._items if i.needs_target)
        with patch.object(app, "prefill_input") as mock_prefill:
            picker._on_select(item)
            mock_prefill.assert_called_once_with(f"/workflow {item.value} ")


class TestSlashCommandDelegation:
    """Verify slash commands delegate to app._submit_user_message."""

    @pytest.mark.asyncio
    async def test_analyze_delegates_to_app_submit(self, app: QuantAgentApp) -> None:
        app.runner = MagicMock()
        with patch.object(app, "_submit_user_message") as mock_submit:
            await _handle_analyze(["AAPL"], app)
            mock_submit.assert_called_once_with("Perform a full analysis of AAPL")

    @pytest.mark.asyncio
    async def test_backtest_delegates_to_app_submit(self, app: QuantAgentApp) -> None:
        app.runner = MagicMock()
        with patch.object(app, "_submit_user_message") as mock_submit:
            await _handle_backtest(["AAPL", "sma"], app)
            mock_submit.assert_called_once_with(
                "Run a backtest for AAPL using sma strategy"
            )

    @pytest.mark.asyncio
    async def test_screen_delegates_to_app_submit(self, app: QuantAgentApp) -> None:
        app.runner = MagicMock()
        with patch.object(app, "_submit_user_message") as mock_submit:
            await _handle_screen(["pe < 20"], app)
            mock_submit.assert_called_once_with("Screen stocks where pe < 20")

    @pytest.mark.asyncio
    async def test_compare_delegates_to_app_submit(self, app: QuantAgentApp) -> None:
        app.runner = MagicMock()
        with patch.object(app, "_submit_user_message") as mock_submit:
            await _handle_compare(["AAPL", "GOOGL"], app)
            mock_submit.assert_called_once_with("Compare AAPL GOOGL")

    @pytest.mark.asyncio
    async def test_warm_defaults_to_sp500(self, app: QuantAgentApp) -> None:
        app.runner = MagicMock()
        with patch.object(app, "_submit_user_message") as mock_submit:
            await _handle_warm([], app)
            mock_submit.assert_called_once()
            assert "'sp500'" in mock_submit.call_args.args[0]

    @pytest.mark.asyncio
    async def test_warm_delegates_to_app_submit(self, app: QuantAgentApp) -> None:
        app.runner = MagicMock()
        with patch.object(app, "_submit_user_message") as mock_submit:
            await _handle_warm(["NASDAQ100"], app)
            mock_submit.assert_called_once()
            assert "'nasdaq100'" in mock_submit.call_args.args[0]

    @pytest.mark.asyncio
    async def test_retry_delegates_to_app_submit(self, app: QuantAgentApp) -> None:
        mock_messages = MagicMock()
        mock_messages.last_user_message.return_value = "previous message"
        app.runner = MagicMock()
        with (
            patch.object(app, "query_one", return_value=mock_messages),
            patch.object(app, "_submit_user_message") as mock_submit,
        ):
            await _handle_retry([], app)
            mock_submit.assert_called_once_with("previous message")

    @pytest.mark.asyncio
    async def test_retry_no_message_shows_error(self, app: QuantAgentApp) -> None:
        mock_messages = MagicMock()
        mock_messages.last_user_message.return_value = None
        with patch.object(app, "query_one", return_value=mock_messages):
            await _handle_retry([], app)
            mock_messages.add_system_message.assert_called_once()

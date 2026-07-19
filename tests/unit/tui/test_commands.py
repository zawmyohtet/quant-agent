from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from quantagent.tui.app import QuantAgentApp
from quantagent.tui.commands import (
    REGISTRY,
    _handle_backtest,
    _handle_report,
    _handle_retry,
    _handle_screen,
    _handle_sector,
    _handle_stock,
    _handle_universe,
    _handle_warm,
    _handle_workflow,
    _render_workflow_result,
    _split_mode,
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

    def test_domain_command_aliases(self) -> None:
        # Old per-feature commands now resolve to the consolidated domain command.
        assert find_command("analyze") is find_command("stock")
        assert find_command("compare") is find_command("stock")
        assert find_command("heatmap") is find_command("market")
        assert find_command("riskgate") is find_command("journal")


class TestSplitMode:
    def test_trailing_mode_extracted(self) -> None:
        assert _split_mode(["AAPL", "MSFT", "quick"], {"quick", "report"}) == (
            "quick",
            ["AAPL", "MSFT"],
        )

    def test_no_mode_returns_default(self) -> None:
        assert _split_mode(["AAPL"], {"quick", "report"}) == ("", ["AAPL"])

    def test_multiword_positional_preserved(self) -> None:
        assert _split_mode(["pe", "<", "20", "report"], {"quick", "report"}) == (
            "report",
            ["pe", "<", "20"],
        )

    def test_empty_args(self) -> None:
        assert _split_mode([], {"quick", "report"}) == ("", [])


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
    async def test_stock_default_delegates_to_app_submit(self, app: QuantAgentApp) -> None:
        app.runner = MagicMock()
        with patch.object(app, "_submit_user_message") as mock_submit:
            await _handle_stock(["AAPL"], app)
            mock_submit.assert_called_once()
            assert "AAPL" in mock_submit.call_args.args[0]

    @pytest.mark.asyncio
    async def test_stock_multi_symbol_compares(self, app: QuantAgentApp) -> None:
        app.runner = MagicMock()
        with patch.object(app, "_submit_user_message") as mock_submit:
            await _handle_stock(["AAPL", "GOOGL"], app)
            mock_submit.assert_called_once_with("Compare AAPL GOOGL")

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


class TestWorkflowResultRendering:
    """Quick mode must render real step values, not dict shapes."""

    def test_renders_real_values(self) -> None:
        import pandas as pd

        result = MagicMock()
        result.step_results = {
            "quote": {"symbol": "AAPL", "price": 200.0},
            "news": [{"title": "Apple hits record"}, {"title": "Analysts upbeat"}],
            "candidates": pd.DataFrame({"symbol": ["AAPL"], "pe": [28.5]}),
        }
        rendered = _render_workflow_result(result)
        assert "AAPL" in rendered
        assert "200" in rendered
        assert "Apple hits record" in rendered
        assert "28.5" in rendered
        # No shape-only descriptions leak through.
        assert "dict (" not in rendered
        assert "list (" not in rendered

    def test_empty_result(self) -> None:
        result = MagicMock()
        result.step_results = {}
        assert _render_workflow_result(result) == "Workflow completed."


class TestDeterministicModes:
    """quick/report modes schedule a deterministic worker, not an agent turn."""

    @pytest.mark.asyncio
    async def test_stock_quick_schedules_worker(self, app: QuantAgentApp) -> None:
        with (
            patch.object(app, "query_one", return_value=MagicMock()),
            patch.object(app, "get_provider", return_value=MagicMock()),
            patch.object(app, "run_worker", side_effect=lambda coro: coro.close()) as worker,
            patch.object(app, "_submit_user_message") as submit,
        ):
            await _handle_stock(["AAPL", "quick"], app)
        worker.assert_called_once()
        submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_stock_report_schedules_worker(self, app: QuantAgentApp) -> None:
        with (
            patch.object(app, "query_one", return_value=MagicMock()),
            patch.object(app, "get_provider", return_value=MagicMock()),
            patch.object(app, "run_worker", side_effect=lambda coro: coro.close()) as worker,
            patch.object(app, "_submit_user_message") as submit,
        ):
            await _handle_stock(["AAPL", "report"], app)
        worker.assert_called_once()
        submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_sector_report_without_name_errors(self, app: QuantAgentApp) -> None:
        messages = MagicMock()
        with (
            patch.object(app, "query_one", return_value=messages),
            patch.object(app, "run_worker") as worker,
            patch.object(app, "_submit_user_message") as submit,
        ):
            await _handle_sector(["report"], app)
        worker.assert_not_called()
        submit.assert_not_called()
        messages.add_system_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_deterministic_blocked_while_running(self, app: QuantAgentApp) -> None:
        app.state.is_running = True
        messages = MagicMock()
        with (
            patch.object(app, "query_one", return_value=messages),
            patch.object(app, "get_provider", return_value=MagicMock()),
            patch.object(app, "run_worker") as worker,
        ):
            await _handle_stock(["AAPL", "quick"], app)
        worker.assert_not_called()
        messages.add_system_message.assert_called_once()

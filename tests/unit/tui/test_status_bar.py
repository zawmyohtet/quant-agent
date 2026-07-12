"""Tests for StatusBar."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from quantagent.tui.config import QuantAgentConfig
from quantagent.tui.session_state import SessionState
from quantagent.tui.widgets.status_bar import StatusBar


def _make_bar(state: SessionState) -> StatusBar:
    """Create a StatusBar with mocked segment widgets."""
    bar = StatusBar(state)
    bar._activity = MagicMock()
    bar._model = MagicMock()
    bar._provider = MagicMock()
    bar._thread = MagicMock()
    bar._tokens = MagicMock()
    return bar


class TestStatusBar:
    def test_idle_state(self) -> None:
        config = QuantAgentConfig(model="openai:gpt-4o", provider="yfinance")
        state = SessionState(config=config)
        bar = _make_bar(state)
        bar.refresh_state()
        assert bar._model.update.call_args[0][0] == "openai:gpt-4o"
        assert bar._provider.update.call_args[0][0] == "yfinance"
        assert "idle" in bar._activity.update.call_args[0][0]

    def test_running_state_shows_activity_and_elapsed(self) -> None:
        config = QuantAgentConfig(model="openai:gpt-4o", provider="yfinance")
        state = SessionState(config=config)
        state.start_turn()
        state.current_activity = "get_stock_data"
        state.turn_started_at = time.monotonic() - 12
        bar = _make_bar(state)
        bar.refresh_state()
        text = bar._activity.update.call_args[0][0]
        assert "get_stock_data" in text
        assert "12s" in text

    def test_running_without_start_time_omits_elapsed(self) -> None:
        config = QuantAgentConfig(model="openai:gpt-4o", provider="yfinance")
        state = SessionState(config=config)
        state.is_running = True
        bar = _make_bar(state)
        bar.refresh_state()
        text = bar._activity.update.call_args[0][0]
        assert "thinking" in text
        assert "s" not in text.split("…")[-1]

    def test_end_turn_resets_activity(self) -> None:
        config = QuantAgentConfig(model="openai:gpt-4o", provider="yfinance")
        state = SessionState(config=config)
        state.start_turn()
        state.end_turn()
        bar = _make_bar(state)
        bar.refresh_state()
        assert "idle" in bar._activity.update.call_args[0][0]

    def test_token_count_formatting(self) -> None:
        config = QuantAgentConfig(model="openai:gpt-4o", provider="yfinance")
        state = SessionState(config=config, token_count=12345)
        bar = _make_bar(state)
        bar.refresh_state()
        assert bar._tokens.update.call_args[0][0] == "12,345 tok"

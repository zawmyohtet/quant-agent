"""Snapshot tests for MessageView visual states."""
from __future__ import annotations

from textual.app import App, ComposeResult

from quantagent.tui.widgets.message_view import MessageView


class _MessageViewEmptyApp(App):
    """Minimal app showing empty MessageView."""

    def compose(self) -> ComposeResult:
        yield MessageView(id="messages")


class _MessageViewWithUserMessageApp(App):
    """Minimal app showing MessageView with a user message."""

    def compose(self) -> ComposeResult:
        yield MessageView(id="messages")

    async def on_mount(self) -> None:
        messages = self.query_one("#messages", MessageView)
        messages.add_user_message("analysis AAPL")


class _MessageViewWithAgentMessageApp(App):
    """Minimal app showing MessageView with an agent response."""

    def compose(self) -> ComposeResult:
        yield MessageView(id="messages")

    async def on_mount(self) -> None:
        messages = self.query_one("#messages", MessageView)
        mid = messages.begin_agent_message()
        messages.append_to_agent_message(mid, "Here is the analysis of AAPL:\n\n- **RSI**: 65.2\n- **MACD**: bullish crossover")


class _MessageViewWithSystemMessageApp(App):
    """Minimal app showing MessageView with a system notification."""

    def compose(self) -> ComposeResult:
        yield MessageView(id="messages")

    async def on_mount(self) -> None:
        messages = self.query_one("#messages", MessageView)
        messages.add_system_message("Model changed to openai:gpt-4o.")


class _MessageViewWithErrorMessageApp(App):
    """Minimal app showing MessageView with a non-retryable error."""

    def compose(self) -> ComposeResult:
        yield MessageView(id="messages")

    async def on_mount(self) -> None:
        messages = self.query_one("#messages", MessageView)
        messages.add_error_message("Rate limit exceeded. Try again in 60s.", retryable=False)


class _MessageViewWithToolCallsApp(App):
    """Minimal app showing MessageView with completed tool call entries."""

    def compose(self) -> ComposeResult:
        yield MessageView(id="messages")

    async def on_mount(self) -> None:
        messages = self.query_one("#messages", MessageView)
        messages.add_tool_call("call-1", "get_ohlcv", {"symbol": "AAPL", "period": "1y"})
        messages.complete_tool_call("call-1", "Retrieved 252 rows of OHLCV data.")


class _MessageViewMultiTurnConversationApp(App):
    """Minimal app showing a multi-turn conversation with correct display order.

    Simulates: user -> tool -> agent -> user -> tool -> agent -> system
    """

    def compose(self) -> ComposeResult:
        yield MessageView(id="messages")

    async def on_mount(self) -> None:
        messages = self.query_one("#messages", MessageView)

        # Turn 1
        messages.add_user_message("analysis AAPL")
        messages.add_tool_call("call-1", "get_ohlcv", {"symbol": "AAPL"})
        messages.complete_tool_call("call-1", "Retrieved 252 rows.")
        mid1 = messages.begin_agent_message()
        messages.append_to_agent_message(mid1, "AAPL shows bullish momentum with RSI at 65.")

        # Turn 2
        messages.add_user_message("what about TSLA?")
        messages.add_tool_call("call-2", "get_quote", {"symbol": "TSLA"})
        messages.complete_tool_call("call-2", "TSLA: $245.50")
        mid2 = messages.begin_agent_message()
        messages.append_to_agent_message(mid2, "TSLA is currently trading at $245.50.")

        # System message
        messages.add_system_message("Model changed to anthropic:claude-3.5.")


class TestMessageViewSnapshots:
    """Visual regression tests for MessageView."""

    def test_empty_state(self, snap_compare: object) -> None:
        assert snap_compare(_MessageViewEmptyApp())

    def test_with_user_message(self, snap_compare: object) -> None:
        assert snap_compare(_MessageViewWithUserMessageApp())

    def test_with_agent_message(self, snap_compare: object) -> None:
        assert snap_compare(_MessageViewWithAgentMessageApp())

    def test_with_system_message(self, snap_compare: object) -> None:
        assert snap_compare(_MessageViewWithSystemMessageApp())

    def test_with_error_message(self, snap_compare: object) -> None:
        assert snap_compare(_MessageViewWithErrorMessageApp())

    def test_with_tool_calls(self, snap_compare: object) -> None:
        assert snap_compare(_MessageViewWithToolCallsApp())

    def test_multi_turn_conversation(self, snap_compare: object) -> None:
        assert snap_compare(_MessageViewMultiTurnConversationApp())

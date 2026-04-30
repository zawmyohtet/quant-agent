from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult

from quantagent.adapter.events import (
    AgentError,
    AgentEvent,
    AgentTextChunk,
    AgentTurnComplete,
    ApprovalRequest,
    SystemNotification,
    ToolCallCompleted,
    ToolCallStarted,
)
from quantagent.adapter.runner import AgentRunner
from quantagent.tui.config import QuantAgentConfig
from quantagent.tui.session_state import SessionState
from quantagent.tui.widgets.approval_dialog import ApprovalDialog
from quantagent.tui.widgets.chat_footer import ChatFooter
from quantagent.tui.widgets.chat_input import ChatInput
from quantagent.tui.widgets.message_view import MessageView
from quantagent.tui.widgets.status_bar import StatusBar
from quantagent.tui.widgets.thread_selector import ThreadSelectorScreen

logger = logging.getLogger(__name__)

_WELCOME_BANNER = """
  ██████╗ ██╗   ██╗ █████╗ ███╗   ██╗████████╗ █████╗  ██████╗ ███████╗███╗   ██╗████████╗
 ██╔═══██╗██║   ██║██╔══██╗████╗  ██║╚══██╔══╝██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝
 ██║   ██║██║   ██║███████║██╔██╗ ██║   ██║   ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║
 ██║▄▄ ██║██║   ██║██╔══██║██║╚██╗██║   ██║   ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║
 ╚██████╔╝╚██████╔╝██║  ██║██║ ╚████║   ██║   ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║
  ╚══▀▀═╝  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝

 Quant Analysis Deep Agent  |  v0.1.0

 Model:    {model}
 Provider: {provider}
 Thread:   #{thread}

 Ask anything about stocks, or type /help for commands.
"""


class QuantAgentApp(App):
    """Root Textual application for QuantAgent."""

    CSS_PATH = Path(__file__).with_suffix(".tcss")
    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+t", "open_threads", "Threads"),
        ("ctrl+n", "new_thread", "New thread"),
        ("ctrl+l", "clear_messages", "Clear"),
        ("escape", "cancel_agent", "Interrupt"),
    ]

    def __init__(self, config: QuantAgentConfig, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.config = config
        self.state = SessionState(config=config)
        self.runner: AgentRunner | None = None
        self._event_consumer: asyncio.Task | None = None

    def compose(self) -> ComposeResult:
        yield MessageView(id="messages")
        yield StatusBar(self.state, id="status-bar")
        yield ChatInput(id="chat-input")
        yield ChatFooter(self.state, id="chat-footer")

    async def on_mount(self) -> None:
        self.runner = AgentRunner(self.state)
        await self.runner.start()

        self._event_consumer = asyncio.create_task(self._consume_events())

        banner = _WELCOME_BANNER.format(
            model=self.state.config.model,
            provider=self.state.config.provider,
            thread=self.state.thread_id[:8],
        )
        messages = self.query_one("#messages", MessageView)
        messages.add_system_message(banner)

        await self.state.upsert_thread(
            thread_id=self.state.thread_id,
            created_at=datetime.now(UTC).isoformat(),
            model=self.state.config.model,
            provider=self.state.config.provider,
            first_message_preview="Welcome",
        )

    async def on_unmount(self) -> None:
        # Cancel any active agent workers first so network I/O tasks
        # receive cancellation and the event loop can close cleanly.
        self.workers.cancel_all()
        await self.workers.wait_for_complete()

        if self._event_consumer and not self._event_consumer.done():
            self._event_consumer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._event_consumer

        if self.runner:
            await self.runner.shutdown()

    async def _consume_events(self) -> None:
        """Consume events from the runner's queue and update the TUI."""
        if self.runner is None:
            return

        queue = self.runner.get_event_queue()
        while True:
            event = await queue.get()
            try:
                await self._handle_event(event)
            except Exception:
                logger.exception("Error handling event: %s", event)

    async def _handle_event(self, event: AgentEvent) -> None:
        """Dispatch an AgentEvent to the appropriate TUI update."""
        messages = self.query_one("#messages", MessageView)

        if isinstance(event, AgentTextChunk):
            if messages._agent_buffer_id:
                messages.append_to_agent_message(messages._agent_buffer_id, event.chunk)
            else:
                mid = messages.begin_agent_message()
                messages.append_to_agent_message(mid, event.chunk)

        elif isinstance(event, ToolCallStarted):
            messages.add_tool_call(event.call_id, event.tool_name, event.args)
            messages._agent_buffer_id = None

        elif isinstance(event, ToolCallCompleted):
            messages.complete_tool_call(event.call_id, event.result)

        elif isinstance(event, AgentError):
            messages.add_error_message(event.message, retryable=event.retryable)

        elif isinstance(event, SystemNotification):
            messages.add_system_message(event.text)

        elif isinstance(event, AgentTurnComplete):
            self.state.is_running = False
            messages._agent_buffer_id = None
            status = self.query_one("#status-bar", StatusBar)
            if hasattr(status, "refresh_state"):
                status.refresh_state()
            footer = self.query_one("#chat-footer", ChatFooter)
            if hasattr(footer, "refresh_state"):
                footer.refresh_state()

        elif isinstance(event, ApprovalRequest):
            await self._handle_approval_request(event)

    async def _handle_approval_request(self, event: ApprovalRequest) -> None:
        """Show approval dialog and relay the decision back to the runner."""
        if self.runner is None:
            return

        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self.push_screen(ApprovalDialog(event.tool_name, event.args, future))
        approved = await future

        self.runner.resolve_approval(approved)

        if not approved:
            messages = self.query_one("#messages", MessageView)
            messages.add_system_message(f"Tool {event.tool_name} rejected by user.")

    async def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        if text.startswith("/"):
            await self._dispatch_slash_command(text)
        else:
            await self._submit_user_message(text)

    async def _dispatch_slash_command(self, raw: str) -> None:
        from quantagent.tui.commands import dispatch

        await dispatch(raw, app=self)

    async def _submit_user_message(self, text: str) -> None:
        if self.state.is_running:
            return
        messages = self.query_one("#messages", MessageView)
        messages._agent_buffer_id = None
        messages.add_user_message(text)
        self.state.is_running = True
        status = self.query_one("#status-bar", StatusBar)
        if hasattr(status, "refresh_state"):
            status.refresh_state()
        footer = self.query_one("#chat-footer", ChatFooter)
        if hasattr(footer, "refresh_state"):
            footer.refresh_state()
        if self.runner:
            self.run_worker(self.runner.run_turn(text), exclusive=True)

    def action_open_threads(self) -> None:
        self.push_screen(ThreadSelectorScreen())

    def action_new_thread(self) -> None:
        self.state.new_thread()
        self.query_one("#messages", MessageView).clear()
        self.query_one("#status-bar", StatusBar).refresh_state()
        self.query_one("#chat-footer", ChatFooter).refresh_state()
        self.query_one("#messages", MessageView).add_system_message("Started new thread.")

    def action_clear_messages(self) -> None:
        self.query_one("#messages", MessageView).clear()

    def action_cancel_agent(self) -> None:
        messages = self.query_one("#messages", MessageView)
        if self.runner:
            self.runner.cancel()
        messages.add_system_message("Agent turn cancelled.")

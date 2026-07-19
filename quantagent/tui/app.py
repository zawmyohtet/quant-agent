from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer
from textual.worker import WorkerCancelled

from quantagent.adapter.events import (
    AgentError,
    AgentEvent,
    AgentTextChunk,
    AgentTurnComplete,
    ApprovalRequest,
    SystemNotification,
    ToolCallCompleted,
    ToolCallStarted,
    ToolProgress,
)
from quantagent.adapter.runner import AgentRunner
from quantagent.tui._history import replay_messages
from quantagent.tui.config import QuantAgentConfig
from quantagent.tui.session_state import SessionState
from quantagent.tui.widgets.approval_dialog import ApprovalDialog
from quantagent.tui.widgets.chat_input import ChatInput
from quantagent.tui.widgets.message_view import MessageView
from quantagent.tui.widgets.status_bar import StatusBar
from quantagent.tui.widgets.thread_selector import ThreadSelectorScreen

logger = logging.getLogger(__name__)

_WORKERS_SHUTDOWN_TIMEOUT_SEC = 25.0

_ID_MESSAGES = "#messages"
_ID_STATUS_BAR = "#status-bar"
_ID_CHAT_INPUT = "#chat-input"

# The ASCII art is ~90 columns wide; fall back to the compact banner below this.
_BANNER_MIN_WIDTH = 94

_WELCOME_BANNER = """
  ██████╗ ██╗   ██╗ █████╗ ███╗   ██╗████████╗ █████╗  ██████╗ ███████╗███╗   ██╗████████╗
 ██╔═══██╗██║   ██║██╔══██╗████╗  ██║╚══██╔══╝██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝
 ██║   ██║██║   ██║███████║██╔██╗ ██║   ██║   ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║
 ██║▄▄ ██║██║   ██║██╔══██║██║╚██╗██║   ██║   ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║
 ╚██████╔╝╚██████╔╝██║  ██║██║ ╚████║   ██║   ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║
  ╚══▀▀═╝  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝

 Quant Analysis Deep Agent  |  v{version}

 Model:    {model}
 Provider: {provider}
 Thread:   #{thread}

 Ask anything about stocks, type /help or press F1 for commands.
"""

_WELCOME_BANNER_COMPACT = """
 ▐█ QUANTAGENT ▌ Quant Analysis Deep Agent v{version}

 Model:    {model}
 Provider: {provider}
 Thread:   #{thread}

 Ask anything about stocks, type /help or press F1 for commands.
"""


def _app_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("quantagent")
    except PackageNotFoundError:
        return "dev"


class QuantAgentApp(App):
    """Root Textual application for QuantAgent."""

    CSS_PATH = Path(__file__).with_suffix(".tcss")
    BINDINGS = [
        Binding("f1", "help", "Help"),
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+t", "open_threads", "Threads"),
        Binding("ctrl+n", "new_thread", "New thread"),
        Binding("ctrl+l", "clear_messages", "Clear"),
        Binding("escape", "cancel_agent", "Interrupt"),
    ]

    def __init__(self, config: QuantAgentConfig, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.config = config
        self.state = SessionState(config=config)
        self.runner: AgentRunner | None = None
        self._event_consumer: asyncio.Task | None = None
        if config.theme in self.available_themes:
            self.theme = config.theme
        else:
            logger.warning("Unknown theme %r in config; using default.", config.theme)

    def watch_theme(self, theme_name: str) -> None:
        """Persist theme changes from any source (/theme, command palette)."""
        if self.config.theme != theme_name:
            self.config.theme = theme_name
            self.config.save()

    def compose(self) -> ComposeResult:
        yield MessageView(id="messages")
        yield StatusBar(self.state, id="status-bar")
        yield ChatInput(id="chat-input")
        yield Footer(id="app-footer")

    async def on_mount(self) -> None:
        self.runner = AgentRunner(self.state)
        await self.runner.start()

        self._event_consumer = asyncio.create_task(self._consume_events())

        template = (
            _WELCOME_BANNER if self.size.width >= _BANNER_MIN_WIDTH else _WELCOME_BANNER_COMPACT
        )
        banner = template.format(
            version=_app_version(),
            model=self.state.config.model,
            provider=self.state.config.provider,
            thread=self.state.thread_id[:8],
        )
        messages = self.query_one(_ID_MESSAGES, MessageView)
        messages.add_system_message(banner)

        # Each launch starts a fresh thread; drop metadata rows left behind by
        # threads that never accumulated any messages.
        await self.state.prune_empty_threads()

    async def on_unmount(self) -> None:
        # Cancel any active agent workers first so network I/O tasks
        # receive cancellation and the event loop can close cleanly.
        if self.runner:
            self.runner.cancel()
        self.workers.cancel_all()
        try:
            await asyncio.wait_for(
                self.workers.wait_for_complete(),
                timeout=_WORKERS_SHUTDOWN_TIMEOUT_SEC,
            )
        except TimeoutError:
            logger.warning(
                "Workers did not finish within %s s during shutdown; continuing cleanup.",
                _WORKERS_SHUTDOWN_TIMEOUT_SEC,
            )
        except WorkerCancelled:
            pass

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
        messages = self.query_one(_ID_MESSAGES, MessageView)

        if isinstance(event, AgentTextChunk):
            if messages._agent_buffer_id:
                messages.append_to_agent_message(messages._agent_buffer_id, event.chunk)
            else:
                mid = messages.begin_agent_message()
                messages.append_to_agent_message(mid, event.chunk)
            self._set_activity("thinking")

        elif isinstance(event, ToolCallStarted):
            messages.add_tool_call(event.call_id, event.tool_name, event.args)
            messages._agent_buffer_id = None
            self._set_activity(event.tool_name)

        elif isinstance(event, ToolCallCompleted):
            messages.complete_tool_call(event.call_id, event.result, is_error=event.is_error)
            self._set_activity("thinking")

        elif isinstance(event, ToolProgress):
            messages.update_tool_progress(event.call_id, event.text)

        elif isinstance(event, AgentError):
            messages.add_error_message(event.message, retryable=event.retryable)

        elif isinstance(event, SystemNotification):
            messages.add_system_message(event.text)

        elif isinstance(event, AgentTurnComplete):
            self.state.end_turn()
            messages._agent_buffer_id = None
            self.query_one(_ID_STATUS_BAR, StatusBar).refresh_state()

        elif isinstance(event, ApprovalRequest):
            await self._handle_approval_request(event)

    def _set_activity(self, activity: str | None) -> None:
        """Update the agent activity shown in the status bar, if it changed."""
        if self.state.current_activity == activity:
            return
        self.state.current_activity = activity
        self.query_one(_ID_STATUS_BAR, StatusBar).refresh_state()

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
            messages = self.query_one(_ID_MESSAGES, MessageView)
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

    async def switch_thread(self, thread_id: str) -> None:
        """Switch to an existing thread and restore its transcript."""
        self.state.thread_id = thread_id
        self.state.config.thread_id = thread_id
        self.state.config.save()

        messages = self.query_one(_ID_MESSAGES, MessageView)
        messages.clear()

        history = await self.runner.load_history(thread_id) if self.runner else []
        replay_messages(history, messages)

        self.query_one(_ID_STATUS_BAR, StatusBar).refresh_state()
        messages.add_system_message(f"Switched to thread #{thread_id[:8]}.")

    async def _submit_user_message(self, text: str) -> None:
        if self.state.is_running:
            return
        messages = self.query_one(_ID_MESSAGES, MessageView)
        messages._agent_buffer_id = None
        messages.add_user_message(text)
        await self.state.note_user_message(text)
        self.state.start_turn()
        self.query_one(_ID_STATUS_BAR, StatusBar).refresh_state()
        if self.runner:
            self.run_worker(self.runner.run_turn(text), exclusive=True)

    def prefill_input(self, text: str) -> None:
        """Put text into the chat input and focus it (e.g. after a picker)."""
        self.query_one(_ID_CHAT_INPUT, ChatInput).set_text(text)

    def action_help(self) -> None:
        from quantagent.tui.widgets.help_screen import HelpScreen

        self.push_screen(HelpScreen())

    def action_open_threads(self) -> None:
        self.push_screen(ThreadSelectorScreen())

    def action_new_thread(self) -> None:
        self.state.new_thread()
        self.query_one(_ID_MESSAGES, MessageView).clear()
        self.query_one(_ID_STATUS_BAR, StatusBar).refresh_state()
        self.query_one(_ID_MESSAGES, MessageView).add_system_message("Started new thread.")

    def action_clear_messages(self) -> None:
        self.query_one(_ID_MESSAGES, MessageView).clear()

    def action_cancel_agent(self) -> None:
        messages = self.query_one(_ID_MESSAGES, MessageView)
        if self.runner:
            self.runner.cancel()
        self.state.end_turn()
        self.query_one(_ID_STATUS_BAR, StatusBar).refresh_state()
        messages.add_system_message("Agent turn cancelled.")

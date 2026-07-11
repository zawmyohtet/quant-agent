"""AgentRunner — bridges the LangGraph agent to the TUI event queue.

The runner owns the agent graph lifetime and streams LangGraph output
(tokens, tool calls, interrupts) into an asyncio.Queue as AgentEvent
instances. The TUI consumes the queue and renders results.

Key responsibilities:
  - Creating the agent via create_quant_agent()
  - Streaming agent responses via astream()
  - Translating LangGraph stream chunks to AgentEvent types
  - Handling HITL interrupts (ApprovalRequest → user decision → resume)
  - Cancellation via asyncio.Task.cancel()
"""
from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
from typing import Any

from quantagent.adapter._interrupt_processing import (
    _process_action_requests,
    _process_single_interrupt,
)
from quantagent.adapter._stream_processing import _StreamProcessor, _TurnContext
from quantagent.adapter.events import (
    AgentError,
    AgentEvent,
    AgentTurnComplete,
    ApprovalRequest,
    SystemNotification,
    ToolProgress,
)
from quantagent.agent.graph import create_quant_agent
from quantagent.tui.session_state import SessionState
from quantagent.utils.progress import set_progress_sink

logger = logging.getLogger(__name__)


class AgentRunner:
    """Orchestrates the LangGraph agent and streams events to the TUI.

    The runner does NOT import any Textual types — it communicates
    exclusively through the asyncio.Queue and ApprovalRequest futures.
    """

    def __init__(self, state: SessionState) -> None:
        self.state = state
        self._queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
        self._agent: Any = None
        self._checkpointer: Any = None
        self._current_task: asyncio.Task | None = None
        self._approval_future: asyncio.Future[bool] | None = None
        self._pending_interrupts: dict[str, Any] = {}

    async def start(self) -> None:
        """Initialize the agent graph and start the event consumer."""
        from quantagent.agent.sessions import get_checkpointer

        try:
            self._checkpointer = await get_checkpointer()
        except Exception:
            logger.exception("Failed to initialize checkpointer")
            await self._queue.put(
                AgentError(message="Failed to initialize session storage.", retryable=True)
            )
            return

        try:
            self._agent = create_quant_agent(
                config=self.state.config,
                checkpointer=self._checkpointer,
                approval_callback=None,
            )
        except Exception:
            logger.exception("Failed to create agent")
            await self._queue.put(
                AgentError(message="Failed to create agent.", retryable=True)
            )
            return

    async def _stop_current_turn_task(self) -> None:
        """Cancel the inner execute task, if any, and wait for it to finish."""
        task = self._current_task
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def run_turn(self, user_message: str) -> None:
        """Process a user message through the agent and stream back results."""
        self.state.is_running = True
        try:
            self._current_task = asyncio.create_task(
                self._execute_turn(user_message)
            )
            await self._current_task
        except asyncio.CancelledError:
            await self._queue.put(SystemNotification(text="Turn cancelled."))
            raise
        except Exception as exc:
            logger.exception("Error in run_turn")
            await self._queue.put(AgentError(message=str(exc), retryable=True))
        finally:
            await self._stop_current_turn_task()
            self._current_task = None
            self.state.is_running = False
            await self._queue.put(AgentTurnComplete())

    async def _execute_turn(self, user_message: str) -> None:
        """Stream the agent response for a single user message."""
        if self._agent is None:
            await self._queue.put(
                AgentError(message="Agent not initialized.", retryable=True)
            )
            return

        config: dict[str, Any] = {
            "configurable": {"thread_id": self.state.thread_id},
        }
        stream_input: dict[str, Any] = {
            "messages": [{"role": "user", "content": user_message}],
        }
        context = _TurnContext()
        processor = _StreamProcessor(
            self._agent, config, self._queue, self._pending_interrupts
        )
        self._install_progress_sink()

        try:
            while True:
                interrupt_occurred = await processor.run(stream_input, context)

                if interrupt_occurred:
                    stream_input = await self._handle_interrupts()
                    if stream_input is None:
                        await self._queue.put(
                            SystemNotification(text="Tool call rejected by user.")
                        )
                        break
                    continue

                break

            self._apply_token_counts(context)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Agent streaming error")
            await self._queue.put(AgentError(message=str(exc), retryable=True))
        finally:
            set_progress_sink(None)

    def _install_progress_sink(self) -> None:
        """Route in-tool progress reports onto the event queue.

        Tools may report from worker threads (``asyncio.to_thread``), so
        the queue put is marshalled back onto the runner's event loop.
        """
        loop = asyncio.get_running_loop()

        def _sink(call_id: str, text: str) -> None:
            loop.call_soon_threadsafe(
                self._queue.put_nowait, ToolProgress(call_id=call_id, text=text)
            )

        set_progress_sink(_sink)

    def _apply_token_counts(self, context: _TurnContext) -> None:
        """Persist token usage from the turn context to session state."""
        if context.total_tokens is not None:
            self.state.token_count += context.total_tokens
        elif context.input_tokens or context.output_tokens:
            self.state.token_count += context.input_tokens + context.output_tokens

    async def _handle_interrupts(self) -> Any:
        """Handle HITL interrupts by requesting user approval.

        Returns a Command(resume=...) to continue the agent, or None
        if all interrupts were rejected (which ends the turn).
        """
        from langgraph.types import Command

        resume_payload: dict[str, Any] = {}
        all_rejected = True

        for interrupt_id, interrupt_data in self._pending_interrupts.items():
            value = interrupt_data["value"]
            action_requests = value.get("action_requests", [])

            if not action_requests:
                result = await _process_single_interrupt(
                    value, self._request_single_approval
                )
            else:
                result = await _process_action_requests(
                    value, self._request_single_approval
                )

            resume_payload[interrupt_id] = result.payload
            if result.was_approved:
                all_rejected = False

        self._pending_interrupts.clear()

        if all_rejected:
            return None

        return Command(resume=resume_payload)

    async def _request_single_approval(
        self, tool_name: str, args: dict[str, Any]
    ) -> bool:
        """Request approval for a single tool call and wait for user decision."""
        loop = asyncio.get_running_loop()
        self._approval_future = loop.create_future()

        call_id = f"hitl-{tool_name}"
        await self._queue.put(
            ApprovalRequest(call_id=call_id, tool_name=tool_name, args=args)
        )

        return await self._approval_future

    def resolve_approval(self, approved: bool) -> None:
        """Resolve a pending ApprovalRequest from the TUI.

        Called by the TUI when the user approves or rejects a tool call.
        """
        if self._approval_future is not None and not self._approval_future.done():
            self._approval_future.set_result(approved)
        self._approval_future = None

    def cancel(self) -> None:
        """Signal the current turn to stop."""
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()

    async def reload_skills(self) -> None:
        """Reload the skill set by recreating the agent."""
        try:
            self._agent = create_quant_agent(
                config=self.state.config,
                checkpointer=self._checkpointer,
                approval_callback=None,
            )
            await self._queue.put(
                SystemNotification(text="Skills reloaded successfully.")
            )
        except Exception as exc:
            logger.exception("Failed to reload skills")
            await self._queue.put(
                AgentError(message=f"Failed to reload skills: {exc}", retryable=True)
            )

    async def set_model(self, model: str) -> None:
        """Update the active model and recreate the agent."""
        self.state.config.model = model
        self.state.config.save()
        try:
            self._agent = create_quant_agent(
                config=self.state.config,
                checkpointer=self._checkpointer,
                approval_callback=None,
            )
            await self._queue.put(
                SystemNotification(text=f"Model changed to {model}.")
            )
        except Exception as exc:
            logger.exception("Failed to change model")
            await self._queue.put(
                AgentError(message=f"Failed to change model: {exc}", retryable=True)
            )

    async def shutdown(self) -> None:
        """Clean up resources on app exit."""
        await self._stop_current_turn_task()
        self._current_task = None

        if self._checkpointer is None:
            return

        cp = self._checkpointer
        self._checkpointer = None
        try:
            close_fn = getattr(cp, "close", None)
            if callable(close_fn):
                maybe = close_fn()
                if inspect.isawaitable(maybe):
                    await maybe
            else:
                conn = getattr(cp, "conn", None)
                if conn is not None:
                    conn_close = getattr(conn, "close", None)
                    if callable(conn_close):
                        maybe_conn = conn_close()
                        if inspect.isawaitable(maybe_conn):
                            await maybe_conn
        except Exception:
            logger.debug("Error closing checkpointer", exc_info=True)

    def get_event_queue(self) -> asyncio.Queue[AgentEvent]:
        """Return the event queue for the TUI to consume."""
        return self._queue

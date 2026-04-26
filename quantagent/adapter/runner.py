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
import json
import logging
from typing import Any

from langchain_core.messages import AIMessageChunk, HumanMessage, ToolMessage

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
from quantagent.agent.graph import create_quant_agent
from quantagent.tui.session_state import SessionState

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
        self._turn_input_tokens = 0
        self._turn_output_tokens = 0
        self._turn_total_tokens: int | None = None

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
        except Exception as exc:
            logger.exception("Error in run_turn")
            await self._queue.put(AgentError(message=str(exc), retryable=True))
        finally:
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

        user_msg = {"role": "user", "content": user_message}
        stream_input: dict[str, Any] = {"messages": [user_msg]}

        tool_call_buffers: dict[str | int, dict[str, Any]] = {}
        displayed_tool_ids: set[str] = set()
        active_message_started = False
        self._turn_input_tokens = 0
        self._turn_output_tokens = 0
        self._turn_total_tokens = None

        try:
            while True:
                interrupt_occurred = False
                self._pending_interrupts.clear()

                async for chunk in self._agent.astream(
                    stream_input,
                    stream_mode=["messages", "updates"],
                    subgraphs=True,
                    config=config,
                ):
                    if not isinstance(chunk, tuple) or len(chunk) != 3:
                        continue

                    namespace, current_stream_mode, data = chunk
                    ns_key = tuple(namespace) if namespace else ()
                    is_main_agent = ns_key == ()

                    if current_stream_mode == "updates":
                        if not isinstance(data, dict):
                            continue

                        if "__interrupt__" in data:
                            interrupts = data["__interrupt__"]
                            for interrupt_obj in interrupts:
                                iv = interrupt_obj.value
                                if isinstance(iv, dict):
                                    self._pending_interrupts[interrupt_obj.id] = {
                                        "interrupt_obj": interrupt_obj,
                                        "value": iv,
                                    }
                                    interrupt_occurred = True

                    elif current_stream_mode == "messages":
                        if not is_main_agent:
                            continue

                        if not isinstance(data, tuple) or len(data) != 2:
                            continue

                        message, metadata = data

                        if isinstance(message, HumanMessage):
                            continue

                        if isinstance(message, ToolMessage):
                            tool_call_id = getattr(message, "tool_call_id", "")
                            content = message.content

                            result_str = str(content) if content else ""
                            await self._queue.put(
                                ToolCallCompleted(
                                    call_id=tool_call_id,
                                    result=result_str,
                                )
                            )
                            continue

                        if not isinstance(message, AIMessageChunk):
                            continue

                        if hasattr(message, "usage_metadata") and message.usage_metadata:
                            usage = message.usage_metadata
                            total = usage.get("total_tokens")
                            if total is not None and total > 0:
                                self._turn_total_tokens = total
                            else:
                                self._turn_input_tokens += usage.get("input_tokens", 0)
                                self._turn_output_tokens += usage.get("output_tokens", 0)

                        if not hasattr(message, "content_blocks"):
                            if (
                                message.content
                                and isinstance(message.content, str)
                                and message.content.strip()
                            ):
                                if not active_message_started:
                                    active_message_started = True
                                await self._queue.put(
                                    AgentTextChunk(chunk=message.content)
                                )
                            continue

                        blocks = message.content_blocks

                        for block in blocks:
                            block_type = block.get("type")

                            if block_type == "text":
                                text = str(block.get("text", ""))
                                if text:
                                    if not active_message_started:
                                        active_message_started = True
                                    await self._queue.put(
                                        AgentTextChunk(chunk=text)
                                    )

                            elif block_type in {"tool_call_chunk", "tool_call"}:
                                chunk_name = block.get("name")
                                chunk_args = block.get("args")
                                chunk_id = block.get("id")
                                chunk_index = block.get("index")

                                buffer_key: str | int
                                if chunk_index is not None:
                                    buffer_key = chunk_index
                                elif chunk_id is not None:
                                    buffer_key = chunk_id
                                else:
                                    buffer_key = f"unknown-{len(tool_call_buffers)}"

                                buffer = tool_call_buffers.setdefault(
                                    buffer_key,
                                    {
                                        "name": None,
                                        "id": None,
                                        "args": None,
                                        "args_parts": [],
                                    },
                                )

                                if chunk_name:
                                    buffer["name"] = chunk_name
                                if chunk_id:
                                    buffer["id"] = chunk_id

                                if isinstance(chunk_args, dict):
                                    buffer["args"] = chunk_args
                                    buffer["args_parts"] = []
                                elif isinstance(chunk_args, str):
                                    if chunk_args:
                                        parts: list[str] = buffer.setdefault(
                                            "args_parts", []
                                        )
                                        if not parts or chunk_args != parts[-1]:
                                            parts.append(chunk_args)
                                        buffer["args"] = "".join(parts)
                                elif chunk_args is not None:
                                    buffer["args"] = chunk_args

                                buffer_name = buffer.get("name")
                                buffer_id = buffer.get("id")
                                if buffer_name is None:
                                    continue

                                parsed_args = buffer.get("args")
                                if isinstance(parsed_args, str):
                                    if not parsed_args:
                                        continue
                                    try:
                                        parsed_args = json.loads(parsed_args)
                                    except json.JSONDecodeError:
                                        continue
                                elif parsed_args is None:
                                    continue

                                if not isinstance(parsed_args, dict):
                                    parsed_args = {"value": parsed_args}

                                if (
                                    buffer_id is not None
                                    and buffer_id not in displayed_tool_ids
                                ):
                                    displayed_tool_ids.add(buffer_id)
                                    await self._queue.put(
                                        ToolCallStarted(
                                            call_id=buffer_id,
                                            tool_name=buffer_name,
                                            args=parsed_args,
                                        )
                                    )

                                tool_call_buffers.pop(buffer_key, None)

                        if getattr(message, "chunk_position", None) == "last":
                            active_message_started = False

                if interrupt_occurred:
                    stream_input = await self._handle_interrupts()
                    if stream_input is None:
                        await self._queue.put(
                            SystemNotification(text="Tool call rejected by user.")
                        )
                        break
                    continue

                break

            if self._turn_total_tokens is not None:
                self.state.token_count += self._turn_total_tokens
            elif self._turn_input_tokens or self._turn_output_tokens:
                self.state.token_count += self._turn_input_tokens + self._turn_output_tokens

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Agent streaming error")
            await self._queue.put(AgentError(message=str(exc), retryable=True))

    async def _handle_interrupts(self) -> Any:
        """Handle HITL interrupts by requesting user approval.

        Returns a Command(resume=...) to continue the agent, or None
        if all interrupts were rejected (which ends the turn).
        """
        from langchain.agents.middleware.human_in_the_loop import (
            ApproveDecision,
            RejectDecision,
        )
        from langgraph.types import Command

        decision_type = ApproveDecision | RejectDecision

        resume_payload: dict[str, Any] = {}
        all_rejected = True

        for interrupt_id, interrupt_data in self._pending_interrupts.items():
            value = interrupt_data["value"]
            tool_name = value.get("tool_name", value.get("name", "unknown"))

            action_requests = value.get("action_requests", [])
            if not action_requests:
                args = {
                    k: v for k, v in value.items()
                    if k not in ("tool_name", "name")
                }
                approved = await self._request_single_approval(tool_name, args)
                if approved:
                    resume_payload[interrupt_id] = [{"type": "approve"}]
                    all_rejected = False
                else:
                    resume_payload[interrupt_id] = [{"type": "reject"}]
            else:
                decisions: list[decision_type] = []
                for ar in action_requests:
                    ar_name = ar.get("name", "unknown")
                    ar_args = ar.get("args", {})
                    approved = await self._request_single_approval(ar_name, ar_args)
                    if approved:
                        decisions.append(ApproveDecision(type="approve"))
                        all_rejected = False
                    else:
                        decisions.append(RejectDecision(type="reject"))
                resume_payload[interrupt_id] = {"decisions": decisions}

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
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
        if self._checkpointer is not None:
            try:
                if hasattr(self._checkpointer, "close"):
                    await self._checkpointer.close()
            except Exception:
                logger.debug("Error closing checkpointer", exc_info=True)

    def get_event_queue(self) -> asyncio.Queue[AgentEvent]:
        """Return the event queue for the TUI to consume."""
        return self._queue

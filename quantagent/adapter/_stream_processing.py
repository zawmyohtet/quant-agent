"""Stream processing utilities for AgentRunner.

Extracts LangGraph stream chunk handling from AgentRunner to keep
cognitive complexity low. Uses Strategy Pattern for mode-specific handling
and Factory/Adapter Pattern for event generation.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from langchain_core.messages import AIMessageChunk, HumanMessage, ToolMessage

from quantagent.adapter.events import (
    AgentEvent,
    AgentTextChunk,
    ToolCallCompleted,
    ToolCallStarted,
)

logger = logging.getLogger(__name__)


class _TurnContext:
    """Mutable state scoped to a single agent turn."""

    def __init__(self) -> None:
        self.tool_call_buffers: dict[str | int, dict[str, Any]] = {}
        self.displayed_tool_ids: set[str] = set()
        self.active_message_started = False
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens: int | None = None


class _ChunkParser:
    """Parse raw LangGraph stream chunks into structured components."""

    @staticmethod
    def parse(chunk: Any) -> tuple[tuple[Any, ...], str, Any] | None:
        """Validate and decompose a LangGraph stream chunk.

        Returns ``(namespace_key, mode, data)`` or ``None`` if malformed.
        """
        if not isinstance(chunk, tuple) or len(chunk) != 3:
            return None
        namespace, mode, data = chunk
        ns_key = tuple(namespace) if namespace else ()
        return ns_key, mode, data

    @staticmethod
    def is_main_agent(ns_key: tuple[Any, ...]) -> bool:
        """Return True if the chunk originated from the root graph."""
        return ns_key == ()


class _UpdatesHandler:
    """Handle ``updates`` stream mode chunks (e.g. ``__interrupt__``)."""

    @staticmethod
    def process(data: Any, pending_interrupts: dict[str, Any]) -> bool:
        """Extract interrupts from an update payload.

        Returns ``True`` if at least one interrupt was captured.
        """
        if not isinstance(data, dict):
            return False
        if "__interrupt__" not in data:
            return False

        interrupts = data["__interrupt__"]
        for interrupt_obj in interrupts:
            iv = interrupt_obj.value
            if isinstance(iv, dict):
                pending_interrupts[interrupt_obj.id] = {
                    "interrupt_obj": interrupt_obj,
                    "value": iv,
                }
        return True


class _MessageDispatcher:
    """Dispatch LangChain messages to the appropriate handler."""

    @staticmethod
    def dispatch(message: Any, context: _TurnContext) -> list[AgentEvent]:
        """Route a message to its handler and return generated events."""
        if isinstance(message, HumanMessage):
            return []

        if isinstance(message, ToolMessage):
            return _MessageDispatcher._handle_tool_message(message)

        if isinstance(message, AIMessageChunk):
            return _AIMessageHandler.process(message, context)

        return []

    @staticmethod
    def _handle_tool_message(message: ToolMessage) -> list[AgentEvent]:
        """Translate a ToolMessage into a ToolCallCompleted event."""
        tool_call_id = getattr(message, "tool_call_id", "")
        content = message.content
        result_str = str(content) if content else ""
        return [ToolCallCompleted(call_id=tool_call_id, result=result_str)]


class _AIMessageHandler:
    """Process AIMessageChunk messages and emit AgentEvents."""

    @staticmethod
    def process(message: AIMessageChunk, context: _TurnContext) -> list[AgentEvent]:
        """Handle token tracking, content extraction, and tool call buffering."""
        events: list[AgentEvent] = []

        _AIMessageHandler._track_tokens(message, context)

        if not hasattr(message, "content_blocks"):
            events.extend(_AIMessageHandler._handle_simple_content(message, context))
            return events

        events.extend(_AIMessageHandler._handle_content_blocks(message, context))

        if getattr(message, "chunk_position", None) == "last":
            context.active_message_started = False

        return events

    @staticmethod
    def _track_tokens(message: AIMessageChunk, context: _TurnContext) -> None:
        """Accumulate token usage from the message's usage_metadata."""
        if hasattr(message, "usage_metadata") and message.usage_metadata:
            usage = message.usage_metadata
            total = usage.get("total_tokens")
            if total is not None and total > 0:
                context.total_tokens = total
            else:
                context.input_tokens += usage.get("input_tokens", 0)
                context.output_tokens += usage.get("output_tokens", 0)

    @staticmethod
    def _handle_simple_content(
        message: AIMessageChunk, context: _TurnContext
    ) -> list[AgentEvent]:
        """Emit AgentTextChunk for plain string content."""
        if (
            message.content
            and isinstance(message.content, str)
            and message.content.strip()
        ):
            context.active_message_started = True
            return [AgentTextChunk(chunk=message.content)]
        return []

    @staticmethod
    def _handle_content_blocks(
        message: AIMessageChunk, context: _TurnContext
    ) -> list[AgentEvent]:
        """Iterate content_blocks and emit events per block type."""
        events: list[AgentEvent] = []
        blocks = message.content_blocks

        for block in blocks:
            event = _AIMessageHandler._process_single_block(block, context)
            if event is not None:
                events.append(event)

        return events

    @staticmethod
    def _process_single_block(block: Any, context: _TurnContext) -> AgentEvent | None:
        """Dispatch a single content block based on its type."""
        if not isinstance(block, dict):
            return None
        block_type = block.get("type")

        if block_type == "text":
            text = str(block.get("text", ""))
            if text:
                context.active_message_started = True
                return AgentTextChunk(chunk=text)
            return None

        if block_type in {"tool_call_chunk", "tool_call"}:
            return _AIMessageHandler._handle_tool_call_block(block, context)

        return None

    @staticmethod
    def _handle_tool_call_block(
        block: dict[str, Any], context: _TurnContext
    ) -> AgentEvent | None:
        """Accumulate tool call chunks and emit ToolCallStarted when complete."""
        buffer_key, buffer_dict = _ToolCallBufferManager.get_or_create_buffer(
            context, block
        )
        _ToolCallBufferManager.update_buffer(buffer_dict, block)
        return _ToolCallBufferManager.try_emit(buffer_key, buffer_dict, context)


class _ToolCallBufferManager:
    """Manage in-flight tool call argument buffering."""

    @staticmethod
    def get_or_create_buffer(
        context: _TurnContext, block: dict[str, Any]
    ) -> tuple[str | int, dict[str, Any]]:
        """Return an existing or new buffer for the given block."""
        chunk_id = block.get("id")
        chunk_index = block.get("index")

        if chunk_index is not None:
            buffer_key: str | int = chunk_index
        elif chunk_id is not None:
            buffer_key = chunk_id
        else:
            buffer_key = f"unknown-{len(context.tool_call_buffers)}"

        buffer_dict = context.tool_call_buffers.setdefault(
            buffer_key,
            {"name": None, "id": None, "args": None, "args_parts": []},
        )
        return buffer_key, buffer_dict

    @staticmethod
    def update_buffer(buffer_dict: dict[str, Any], block: dict[str, Any]) -> None:
        """Merge the latest block fields into the buffer."""
        if chunk_name := block.get("name"):
            buffer_dict["name"] = chunk_name
        if chunk_id := block.get("id"):
            buffer_dict["id"] = chunk_id

        chunk_args = block.get("args")
        if isinstance(chunk_args, dict):
            buffer_dict["args"] = chunk_args
            buffer_dict["args_parts"] = []
        elif isinstance(chunk_args, str):
            if chunk_args:
                parts: list[str] = buffer_dict.setdefault("args_parts", [])
                if not parts or chunk_args != parts[-1]:
                    parts.append(chunk_args)
                buffer_dict["args"] = "".join(parts)
        elif chunk_args is not None:
            buffer_dict["args"] = chunk_args

    @staticmethod
    def try_emit(
        buffer_key: str | int,
        buffer_dict: dict[str, Any],
        context: _TurnContext,
    ) -> AgentEvent | None:
        """If the buffer is complete and unseen, emit ``ToolCallStarted``."""
        buffer_name = buffer_dict.get("name")
        buffer_id = buffer_dict.get("id")
        if buffer_name is None:
            return None

        parsed_args = _ToolCallBufferManager._parse_args(buffer_dict.get("args"))
        if parsed_args is None:
            return None

        if buffer_id is not None and buffer_id not in context.displayed_tool_ids:
            context.displayed_tool_ids.add(buffer_id)
            context.tool_call_buffers.pop(buffer_key, None)
            return ToolCallStarted(
                call_id=buffer_id,
                tool_name=buffer_name,
                args=parsed_args,
            )

        context.tool_call_buffers.pop(buffer_key, None)
        return None

    @staticmethod
    def _parse_args(args: Any) -> dict[str, Any] | None:
        """Normalise arguments to a dict, or return None if incomplete."""
        if isinstance(args, dict):
            return args
        if isinstance(args, str):
            if not args:
                return None
            try:
                parsed = json.loads(args)
                if isinstance(parsed, dict):
                    return parsed
                return {"value": parsed}
            except json.JSONDecodeError:
                return None
        if args is None:
            return None
        return {"value": args}


class _StreamProcessor:
    """Orchestrate one iteration of the LangGraph astream loop."""

    def __init__(
        self,
        agent: Any,
        config: dict[str, Any],
        queue: asyncio.Queue[AgentEvent],
        pending_interrupts: dict[str, Any],
    ) -> None:
        self._agent = agent
        self._config = config
        self._queue = queue
        self._pending_interrupts = pending_interrupts

    async def run(self, stream_input: dict[str, Any], context: _TurnContext) -> bool:
        """Stream one pass and return whether an interrupt occurred."""
        interrupt_occurred = False
        self._pending_interrupts.clear()

        async for chunk in self._agent.astream(
            stream_input,
            stream_mode=["messages", "updates"],
            subgraphs=True,
            config=self._config,
        ):
            parsed = _ChunkParser.parse(chunk)
            if parsed is None:
                continue

            ns_key, mode, data = parsed

            if mode == "updates":
                if _UpdatesHandler.process(data, self._pending_interrupts):
                    interrupt_occurred = True
                continue

            if mode == "messages":
                await self._process_message_chunk(ns_key, data, context)

        return interrupt_occurred

    async def _process_message_chunk(
        self,
        ns_key: tuple[Any, ...],
        data: Any,
        context: _TurnContext,
    ) -> None:
        """Handle a single ``messages`` mode chunk from the main agent."""
        if not _ChunkParser.is_main_agent(ns_key):
            return
        if not isinstance(data, tuple) or len(data) != 2:
            return

        message, _metadata = data
        events = _MessageDispatcher.dispatch(message, context)
        for event in events:
            await self._queue.put(event)

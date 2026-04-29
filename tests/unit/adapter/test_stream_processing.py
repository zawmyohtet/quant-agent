"""Tests for _stream_processing module."""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessageChunk, HumanMessage, ToolMessage

from quantagent.adapter._stream_processing import (
    _AIMessageHandler,
    _ChunkParser,
    _MessageDispatcher,
    _StreamProcessor,
    _ToolCallBufferManager,
    _TurnContext,
    _UpdatesHandler,
)
from quantagent.adapter.events import (
    AgentTextChunk,
    ToolCallCompleted,
    ToolCallStarted,
)


class TestChunkParser:
    def test_parse_valid_tuple(self) -> None:
        chunk = (["ns"], "messages", "data")
        result = _ChunkParser.parse(chunk)
        assert result is not None
        assert result[0] == ("ns",)
        assert result[1] == "messages"
        assert result[2] == "data"

    def test_parse_empty_namespace(self) -> None:
        chunk = ([], "updates", {})
        result = _ChunkParser.parse(chunk)
        assert result is not None
        assert result[0] == ()

    def test_parse_invalid_length(self) -> None:
        assert _ChunkParser.parse(("a", "b")) is None

    def test_parse_non_tuple(self) -> None:
        assert _ChunkParser.parse("not-a-tuple") is None

    def test_is_main_agent_true(self) -> None:
        assert _ChunkParser.is_main_agent(()) is True

    def test_is_main_agent_false(self) -> None:
        assert _ChunkParser.is_main_agent(("subgraph",)) is False


class TestUpdatesHandler:
    def test_process_with_interrupt(self) -> None:
        pending: dict[str, Any] = {}
        interrupt_obj = MagicMock()
        interrupt_obj.value = {"tool_name": "test_tool"}
        interrupt_obj.id = "int-1"
        data = {"__interrupt__": [interrupt_obj]}

        result = _UpdatesHandler.process(data, pending)

        assert result is True
        assert "int-1" in pending
        assert pending["int-1"]["value"]["tool_name"] == "test_tool"

    def test_process_without_interrupt(self) -> None:
        pending: dict[str, Any] = {}
        result = _UpdatesHandler.process({"other_key": []}, pending)
        assert result is False
        assert len(pending) == 0

    def test_process_non_dict_data(self) -> None:
        pending: dict[str, Any] = {}
        result = _UpdatesHandler.process("not-a-dict", pending)
        assert result is False

    def test_process_skips_non_dict_values(self) -> None:
        pending: dict[str, Any] = {}
        interrupt_obj = MagicMock()
        interrupt_obj.value = "not-a-dict"
        interrupt_obj.id = "int-1"
        data = {"__interrupt__": [interrupt_obj]}

        result = _UpdatesHandler.process(data, pending)

        assert result is True
        assert len(pending) == 0


class TestMessageDispatcher:
    def test_dispatch_human_message(self) -> None:
        context = _TurnContext()
        msg = HumanMessage(content="hello")
        events = _MessageDispatcher.dispatch(msg, context)
        assert events == []

    def test_dispatch_tool_message(self) -> None:
        context = _TurnContext()
        msg = ToolMessage(content="result", tool_call_id="tc-1")
        events = _MessageDispatcher.dispatch(msg, context)
        assert len(events) == 1
        assert isinstance(events[0], ToolCallCompleted)
        assert events[0].call_id == "tc-1"
        assert events[0].result == "result"

    def test_dispatch_unknown_message(self) -> None:
        context = _TurnContext()
        events = _MessageDispatcher.dispatch("unknown", context)
        assert events == []


class TestAIMessageHandler:
    def test_track_tokens_total(self) -> None:
        context = _TurnContext()
        msg = MagicMock()
        msg.usage_metadata = {"total_tokens": 42}
        _AIMessageHandler._track_tokens(msg, context)  # type: ignore[arg-type]
        assert context.total_tokens == 42
        assert context.input_tokens == 0
        assert context.output_tokens == 0

    def test_track_tokens_input_output(self) -> None:
        context = _TurnContext()
        msg = MagicMock()
        msg.usage_metadata = {"input_tokens": 10, "output_tokens": 20}
        _AIMessageHandler._track_tokens(msg, context)  # type: ignore[arg-type]
        assert context.total_tokens is None
        assert context.input_tokens == 10
        assert context.output_tokens == 20

    def test_handle_simple_content_valid(self) -> None:
        context = _TurnContext()
        msg = AIMessageChunk(content="hello world")
        events = _AIMessageHandler._handle_simple_content(msg, context)
        assert len(events) == 1
        assert isinstance(events[0], AgentTextChunk)
        assert events[0].chunk == "hello world"
        assert context.active_message_started is True

    def test_handle_simple_content_empty(self) -> None:
        context = _TurnContext()
        msg = AIMessageChunk(content="   ")
        events = _AIMessageHandler._handle_simple_content(msg, context)
        assert events == []

    def test_handle_simple_content_non_string(self) -> None:
        context = _TurnContext()
        msg = AIMessageChunk(content=["not", "string"])  # type: ignore[arg-type]
        events = _AIMessageHandler._handle_simple_content(msg, context)
        assert events == []

    def test_process_single_block_text(self) -> None:
        context = _TurnContext()
        block = {"type": "text", "text": "chunk"}
        event = _AIMessageHandler._process_single_block(block, context)
        assert isinstance(event, AgentTextChunk)
        assert event.chunk == "chunk"

    def test_process_single_block_text_empty(self) -> None:
        context = _TurnContext()
        block = {"type": "text", "text": ""}
        event = _AIMessageHandler._process_single_block(block, context)
        assert event is None

    def test_process_single_block_non_dict(self) -> None:
        context = _TurnContext()
        event = _AIMessageHandler._process_single_block("not-dict", context)
        assert event is None

    def test_process_single_block_unknown_type(self) -> None:
        context = _TurnContext()
        block = {"type": "image", "url": "http://example.com"}
        event = _AIMessageHandler._process_single_block(block, context)
        assert event is None

    def test_process_resets_active_on_last_chunk(self) -> None:
        context = _TurnContext()
        context.active_message_started = True
        msg = AIMessageChunk(content="hi")
        msg.chunk_position = "last"  # type: ignore[attr-defined]
        events = _AIMessageHandler.process(msg, context)
        assert context.active_message_started is False
        assert len(events) == 1


class TestToolCallBufferManager:
    def test_get_or_create_buffer_by_index(self) -> None:
        context = _TurnContext()
        block = {"index": 0}
        key, buf = _ToolCallBufferManager.get_or_create_buffer(context, block)
        assert key == 0
        assert buf["name"] is None

    def test_get_or_create_buffer_by_id(self) -> None:
        context = _TurnContext()
        block = {"id": "tc-1"}
        key, buf = _ToolCallBufferManager.get_or_create_buffer(context, block)
        assert key == "tc-1"

    def test_get_or_create_buffer_unknown(self) -> None:
        context = _TurnContext()
        block = {}
        key, buf = _ToolCallBufferManager.get_or_create_buffer(context, block)
        assert key == "unknown-0"

    def test_update_buffer_sets_name_and_id(self) -> None:
        buf: dict[str, Any] = {"name": None, "id": None, "args": None, "args_parts": []}
        block = {"name": "fetch", "id": "tc-1"}
        _ToolCallBufferManager.update_buffer(buf, block)
        assert buf["name"] == "fetch"
        assert buf["id"] == "tc-1"

    def test_update_buffer_dict_args(self) -> None:
        buf: dict[str, Any] = {"name": None, "id": None, "args": None, "args_parts": []}
        block = {"args": {"symbol": "AAPL"}}
        _ToolCallBufferManager.update_buffer(buf, block)
        assert buf["args"] == {"symbol": "AAPL"}
        assert buf["args_parts"] == []

    def test_update_buffer_string_args(self) -> None:
        buf: dict[str, Any] = {"name": None, "id": None, "args": None, "args_parts": []}
        block = {"args": '{"sym'}
        _ToolCallBufferManager.update_buffer(buf, block)
        assert buf["args_parts"] == ['{"sym']

        block = {"args": 'bol": "AAPL"}'}
        _ToolCallBufferManager.update_buffer(buf, block)
        assert buf["args"] == '{"symbol": "AAPL"}'

    def test_try_emit_not_ready_no_name(self) -> None:
        context = _TurnContext()
        buf = {"name": None, "id": "tc-1", "args": {"x": 1}, "args_parts": []}
        event = _ToolCallBufferManager.try_emit("k", buf, context)
        assert event is None

    def test_try_emit_not_ready_no_args(self) -> None:
        context = _TurnContext()
        buf = {"name": "fetch", "id": "tc-1", "args": None, "args_parts": []}
        event = _ToolCallBufferManager.try_emit("k", buf, context)
        assert event is None

    def test_try_emit_ready(self) -> None:
        context = _TurnContext()
        buf = {"name": "fetch", "id": "tc-1", "args": {"sym": "AAPL"}, "args_parts": []}
        event = _ToolCallBufferManager.try_emit("k", buf, context)
        assert isinstance(event, ToolCallStarted)
        assert event.tool_name == "fetch"
        assert event.call_id == "tc-1"
        assert "k" not in context.tool_call_buffers

    def test_try_emit_already_displayed(self) -> None:
        context = _TurnContext()
        context.displayed_tool_ids.add("tc-1")
        buf = {"name": "fetch", "id": "tc-1", "args": {"sym": "AAPL"}, "args_parts": []}
        event = _ToolCallBufferManager.try_emit("k", buf, context)
        assert event is None
        assert "k" not in context.tool_call_buffers

    def test_parse_args_dict(self) -> None:
        assert _ToolCallBufferManager._parse_args({"x": 1}) == {"x": 1}

    def test_parse_args_valid_json(self) -> None:
        assert _ToolCallBufferManager._parse_args('{"x": 1}') == {"x": 1}

    def test_parse_args_json_non_dict(self) -> None:
        assert _ToolCallBufferManager._parse_args("42") == {"value": 42}

    def test_parse_args_invalid_json(self) -> None:
        assert _ToolCallBufferManager._parse_args("not-json") is None

    def test_parse_args_empty_string(self) -> None:
        assert _ToolCallBufferManager._parse_args("") is None

    def test_parse_args_none(self) -> None:
        assert _ToolCallBufferManager._parse_args(None) is None

    def test_parse_args_scalar(self) -> None:
        assert _ToolCallBufferManager._parse_args(42) == {"value": 42}


class TestStreamProcessor:
    @pytest.mark.asyncio
    async def test_run_no_chunks(self) -> None:
        agent = MagicMock()
        agent.astream = _make_astream([])
        queue: asyncio.Queue = asyncio.Queue()
        pending: dict[str, Any] = {}
        context = _TurnContext()
        processor = _StreamProcessor(agent, {}, queue, pending)

        interrupt = await processor.run({"messages": []}, context)
        assert interrupt is False
        assert queue.empty()

    @pytest.mark.asyncio
    async def test_run_text_chunk(self) -> None:
        msg = AIMessageChunk(content="hello")
        chunk = ((), "messages", (msg, {}))
        agent = MagicMock()
        agent.astream = _make_astream([chunk])
        queue: asyncio.Queue = asyncio.Queue()
        pending: dict[str, Any] = {}
        context = _TurnContext()
        processor = _StreamProcessor(agent, {}, queue, pending)

        interrupt = await processor.run({"messages": []}, context)
        assert interrupt is False
        assert queue.qsize() == 1
        event = queue.get_nowait()
        assert isinstance(event, AgentTextChunk)
        assert event.chunk == "hello"

    @pytest.mark.asyncio
    async def test_run_interrupt_update(self) -> None:
        interrupt_obj = MagicMock()
        interrupt_obj.value = {"tool_name": "fetch"}
        interrupt_obj.id = "int-1"
        chunk = ((), "updates", {"__interrupt__": [interrupt_obj]})
        agent = MagicMock()
        agent.astream = _make_astream([chunk])
        queue: asyncio.Queue = asyncio.Queue()
        pending: dict[str, Any] = {}
        context = _TurnContext()
        processor = _StreamProcessor(agent, {}, queue, pending)

        interrupt = await processor.run({"messages": []}, context)
        assert interrupt is True
        assert "int-1" in pending

    @pytest.mark.asyncio
    async def test_run_skips_subgraph_messages(self) -> None:
        msg = AIMessageChunk(content="hello")
        chunk = (("sub",), "messages", (msg, {}))
        agent = MagicMock()
        agent.astream = _make_astream([chunk])
        queue: asyncio.Queue = asyncio.Queue()
        pending: dict[str, Any] = {}
        context = _TurnContext()
        processor = _StreamProcessor(agent, {}, queue, pending)

        interrupt = await processor.run({"messages": []}, context)
        assert interrupt is False
        assert queue.empty()

    @pytest.mark.asyncio
    async def test_run_skips_invalid_message_data(self) -> None:
        chunk = ((), "messages", "not-a-tuple")
        agent = MagicMock()
        agent.astream = _make_astream([chunk])
        queue: asyncio.Queue = asyncio.Queue()
        pending: dict[str, Any] = {}
        context = _TurnContext()
        processor = _StreamProcessor(agent, {}, queue, pending)

        interrupt = await processor.run({"messages": []}, context)
        assert interrupt is False
        assert queue.empty()

    @pytest.mark.asyncio
    async def test_run_tool_message(self) -> None:
        msg = ToolMessage(content="done", tool_call_id="tc-1")
        chunk = ((), "messages", (msg, {}))
        agent = MagicMock()
        agent.astream = _make_astream([chunk])
        queue: asyncio.Queue = asyncio.Queue()
        pending: dict[str, Any] = {}
        context = _TurnContext()
        processor = _StreamProcessor(agent, {}, queue, pending)

        await processor.run({"messages": []}, context)
        event = queue.get_nowait()
        assert isinstance(event, ToolCallCompleted)


def _make_astream(items: list[Any]) -> Any:
    """Return an async generator function that yields the given items."""
    async def _astream(*args: Any, **kwargs: Any) -> Any:
        for item in items:
            yield item
    return _astream

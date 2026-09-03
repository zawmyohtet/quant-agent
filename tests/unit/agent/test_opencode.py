from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import pytest
from langchain_core.runnables.config import var_child_runnable_config

from quantagent.agent.opencode import SESSION_HEADER, SessionHeaderHook, build_http_clients


@contextmanager
def thread(thread_id: str) -> Iterator[None]:
    """Simulate being inside a langgraph run for ``thread_id``."""
    token = var_child_runnable_config.set({"configurable": {"thread_id": thread_id}})
    try:
        yield
    finally:
        var_child_runnable_config.reset(token)


def test_current_session_id_uses_active_thread_id() -> None:
    with thread("t-1"):
        assert SessionHeaderHook().current_session_id() == "t-1"


def test_current_session_id_falls_back_to_stable_value_outside_run() -> None:
    hook = SessionHeaderHook()
    first = hook.current_session_id()
    second = hook.current_session_id()
    assert first and first == second


def test_fallback_session_is_injectable() -> None:
    assert SessionHeaderHook(fallback_session="fixed").current_session_id() == "fixed"


def _capturing_transport(seen: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers[SESSION_HEADER])
        return httpx.Response(200, json={})

    return httpx.MockTransport(handler)


def test_sync_client_header_follows_thread_on_same_client() -> None:
    seen: list[str] = []
    client, _ = build_http_clients(transport=_capturing_transport(seen))

    with thread("thread-a"):
        client.get("https://opencode.test/v1/x")
    with thread("thread-b"):
        client.get("https://opencode.test/v1/x")

    assert seen == ["thread-a", "thread-b"]


@pytest.mark.asyncio
async def test_async_client_header_follows_thread_on_same_client() -> None:
    seen: list[str] = []
    _, client = build_http_clients(transport=_capturing_transport(seen))

    with thread("thread-a"):
        await client.get("https://opencode.test/v1/x")
    with thread("thread-b"):
        await client.get("https://opencode.test/v1/x")

    assert seen == ["thread-a", "thread-b"]

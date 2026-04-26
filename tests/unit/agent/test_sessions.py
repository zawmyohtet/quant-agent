"""Tests for session persistence."""
from __future__ import annotations

import pytest

from quantagent.agent.sessions import delete_thread, list_threads, new_thread_id


@pytest.mark.asyncio
async def test_new_thread_id():
    tid = new_thread_id()
    assert isinstance(tid, str)
    assert len(tid) > 0


@pytest.mark.asyncio
async def test_list_threads_empty():
    # Uses default DB path which may or may not exist
    threads = await list_threads()
    assert isinstance(threads, list)


@pytest.mark.asyncio
async def test_delete_thread_no_crash():
    # Should not raise even if thread doesn't exist
    await delete_thread("nonexistent-thread-id")

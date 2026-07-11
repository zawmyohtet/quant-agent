"""Tests for the progress channel."""
from __future__ import annotations

import asyncio

import pytest

from quantagent.utils.progress import (
    bind_call_id,
    report_progress,
    set_progress_sink,
)


@pytest.fixture(autouse=True)
def _clean_sink():
    yield
    set_progress_sink(None)


def test_report_without_sink_is_noop() -> None:
    report_progress("nothing happens")  # must not raise


def test_sink_receives_call_id_and_text() -> None:
    received: list[tuple[str, str]] = []
    set_progress_sink(lambda call_id, text: received.append((call_id, text)))
    with bind_call_id("call-42"):
        report_progress("step 1/4")
    assert received == [("call-42", "step 1/4")]


def test_call_id_defaults_to_empty() -> None:
    received: list[tuple[str, str]] = []
    set_progress_sink(lambda call_id, text: received.append((call_id, text)))
    report_progress("untagged")
    assert received == [("", "untagged")]


def test_bind_call_id_scoping() -> None:
    received: list[str] = []
    set_progress_sink(lambda call_id, text: received.append(call_id))
    with bind_call_id("outer"):
        with bind_call_id("inner"):
            report_progress("x")
        report_progress("y")
    report_progress("z")
    assert received == ["inner", "outer", ""]


def test_sink_exception_swallowed() -> None:
    def _boom(call_id: str, text: str) -> None:
        raise RuntimeError("sink broke")

    set_progress_sink(_boom)
    report_progress("still fine")  # must not raise


def test_clearing_sink() -> None:
    received: list[str] = []
    set_progress_sink(lambda call_id, text: received.append(text))
    report_progress("one")
    set_progress_sink(None)
    report_progress("two")
    assert received == ["one"]


async def test_call_id_propagates_to_thread() -> None:
    received: list[tuple[str, str]] = []
    set_progress_sink(lambda call_id, text: received.append((call_id, text)))

    def _worker() -> None:
        report_progress("from thread")

    with bind_call_id("call-7"):
        await asyncio.to_thread(_worker)
    assert received == [("call-7", "from thread")]

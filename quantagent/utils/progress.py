"""Progress channel: tools report progress, the TUI displays it live.

This module is the neutral meeting point allowed by the dependency
rules (every layer may import ``utils/``):

- ``tools/`` call :func:`report_progress` from long-running operations.
- ``agent/`` middleware binds the active tool-call id around each tool
  invocation via :func:`bind_call_id`.
- ``adapter/`` installs a sink via :func:`set_progress_sink` that turns
  reports into TUI events.

When no sink is installed (tests, scripts), reporting is a no-op.
Progress must never break a tool: sink exceptions are swallowed.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

logger = logging.getLogger(__name__)

ProgressSink = Callable[[str, str], None]

_sink: ProgressSink | None = None
_current_call_id: ContextVar[str] = ContextVar("progress_call_id", default="")


def set_progress_sink(sink: ProgressSink | None) -> None:
    """Install (or clear, with None) the global progress sink.

    The sink receives ``(call_id, text)`` and must be safe to call from
    worker threads (e.g. wrap queue puts in ``loop.call_soon_threadsafe``).
    """
    global _sink
    _sink = sink


@contextmanager
def bind_call_id(call_id: str) -> Iterator[None]:
    """Tag progress reported inside this context with ``call_id``.

    Context variables propagate into ``asyncio`` tasks and
    ``asyncio.to_thread`` workers created within the context.
    """
    token = _current_call_id.set(call_id)
    try:
        yield
    finally:
        _current_call_id.reset(token)


def report_progress(text: str) -> None:
    """Report human-readable progress from a long-running operation.

    No-op when no sink is installed. Never raises.
    """
    sink = _sink
    if sink is None:
        return
    try:
        sink(_current_call_id.get(), text)
    except Exception:  # pragma: no cover - defensive; sink must not break tools
        logger.debug("Progress sink failed", exc_info=True)

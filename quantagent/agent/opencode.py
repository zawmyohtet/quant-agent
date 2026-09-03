"""OpenCode Go transport helpers.

OpenCode Go requires every request to carry an ``x-opencode-session`` header
that identifies the conversation; it uses the value for prompt-cache routing,
so it must change when the user switches threads.

The header is injected at the httpx transport layer rather than via
``default_headers`` so that a single chat model / agent instance can serve many
threads without being rebuilt: the request hook reads the active langgraph
``configurable.thread_id`` at send time. Because it sits below the openai SDK,
it also covers calls that bypass agent middleware (summarization, sub-agents).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx
import openai
from langgraph.config import get_config

logger = logging.getLogger(__name__)

SESSION_HEADER = "x-opencode-session"


class SessionHeaderHook:
    """httpx request hook that stamps the active thread id into the session header.

    Args:
        fallback_session: Value used when a request is made outside a langgraph
            run (no thread id available). Defaults to a fresh UUID per instance.
    """

    def __init__(self, fallback_session: str | None = None) -> None:
        self.fallback_session = fallback_session or str(uuid.uuid4())

    def current_session_id(self) -> str:
        """Return the active thread id, or this hook's stable fallback."""
        try:
            thread_id = get_config().get("configurable", {}).get("thread_id")
        except RuntimeError:  # not inside a langgraph run
            thread_id = None
        if not thread_id:
            logger.debug("No active thread id; using fallback %s", SESSION_HEADER)
            return self.fallback_session
        return str(thread_id)

    def __call__(self, request: httpx.Request) -> None:
        """Sync httpx ``request`` event hook."""
        request.headers[SESSION_HEADER] = self.current_session_id()

    async def acall(self, request: httpx.Request) -> None:
        """Async httpx ``request`` event hook."""
        self(request)


def build_http_clients(
    hook: SessionHeaderHook | None = None, **kwargs: Any
) -> tuple[httpx.Client, httpx.AsyncClient]:
    """Build sync + async httpx clients that stamp the session header per request.

    Uses the openai SDK's default client classes so timeouts/limits match what
    the SDK would otherwise create.

    Args:
        hook: Header hook shared by both clients. A new one is created if omitted.
        **kwargs: Forwarded to both clients (e.g. ``transport``) — mainly for tests.

    Returns:
        A ``(sync_client, async_client)`` pair.
    """
    hook = hook or SessionHeaderHook()
    return (
        openai.DefaultHttpxClient(event_hooks={"request": [hook]}, **kwargs),
        openai.DefaultAsyncHttpxClient(event_hooks={"request": [hook.acall]}, **kwargs),
    )

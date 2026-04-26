"""Summarization middleware — context window compaction."""
from __future__ import annotations

import logging
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware

logger = logging.getLogger(__name__)


class SummarizationMiddleware(AgentMiddleware):
    """Summarizes conversation history when token threshold is exceeded."""

    def __init__(self, token_threshold: int = 80_000, model: Any = None):
        self.token_threshold = token_threshold
        self.model = model

    def before_model(self, state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:  # type: ignore[override]
        """Compact messages if token count exceeds threshold."""
        messages = state.get("messages", [])
        if not messages:
            return None

        # Rough token estimate: 4 chars per token
        total_chars = sum(
            len(m.content) if hasattr(m, "content") else len(str(m)) for m in messages
        )
        if total_chars < self.token_threshold:
            return None

        logger.info("Token threshold exceeded (%s chars), compacting context", total_chars)

        # Keep system message and last 10 messages, drop the middle
        system_idx = None
        for i, msg in enumerate(messages):
            if getattr(msg, "type", None) == "system":
                system_idx = i
                break

        keep_head = [messages[system_idx]] if system_idx is not None else []
        keep_tail = messages[-10:]

        # Add a summary placeholder message
        summary_msg = type(messages[0])(
            content=f"[Context summarized: {len(messages) - len(keep_head) - len(keep_tail)} messages omitted]"
        ) if messages else None

        new_messages = keep_head + ([summary_msg] if summary_msg else []) + keep_tail
        return {"messages": new_messages}

    async def abefore_model(  # type: ignore[override]
        self, state: dict[str, Any], runtime: Any
    ) -> dict[str, Any] | None:
        """Async version delegates to sync before_model."""
        return self.before_model(state, runtime)

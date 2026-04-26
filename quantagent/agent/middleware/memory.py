"""Memory middleware — injects QUANTAGENT.md into system prompt."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware


class QuantMemoryMiddleware(AgentMiddleware):
    """Appends QUANTAGENT.md to the system prompt each turn."""

    MEMORY_PATH = Path.home() / ".quantagent" / "QUANTAGENT.md"

    def before_model(self, state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:  # type: ignore[override]
        """Inject memory into the system message before model call."""
        if not self.MEMORY_PATH.exists():
            return None

        memory = self.MEMORY_PATH.read_text().strip()
        if not memory:
            return None

        messages = state.get("messages", [])
        for i, msg in enumerate(messages):
            if getattr(msg, "type", None) == "system":
                original = msg.content if hasattr(msg, "content") else str(msg)
                updated = f"{original}\n\n## Personal Context\n\n{memory}"
                messages[i] = type(msg)(content=updated)
                break

        return {"messages": messages}

    async def abefore_model(  # type: ignore[override]
        self, state: dict[str, Any], runtime: Any
    ) -> dict[str, Any] | None:
        """Async version delegates to sync before_model."""
        return self.before_model(state, runtime)

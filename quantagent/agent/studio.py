"""LangGraph Studio entrypoint.

This module provides a no-argument ``get_graph()`` factory that LangGraph
Studio can import and run. It assembles the quant agent with default
configuration, an in-memory SQLite checkpointer, and the full tool/skill
stack so the graph is fully interactive in the Studio UI.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver

from quantagent.agent.graph import create_quant_agent
from quantagent.tui.config import QuantAgentConfig, load_dotenv_file

logger = logging.getLogger(__name__)


def get_graph() -> Any:
    """Return a compiled LangGraph agent for LangGraph Studio.

    Studio calls this function (no arguments) to obtain the graph it will
    visualise and interact with. We wire up the same production agent but
    with a default ``QuantAgentConfig`` and a persistent SQLite checkpointer.
    """
    load_dotenv_file()
    config = QuantAgentConfig.load()

    # Use a dedicated Studio DB so it does not clobber the user's sessions
    studio_db = Path.home() / ".quantagent" / "studio_sessions.db"
    studio_db.parent.mkdir(parents=True, exist_ok=True)

    with SqliteSaver.from_conn_string(str(studio_db)) as saver:
        return create_quant_agent(
            config=config,
            checkpointer=saver,
            approval_callback=None,  # Studio runs headless — auto-approve all tools
        )

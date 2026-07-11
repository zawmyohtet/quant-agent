"""Shared ~/.quantagent filesystem paths for tools modules.

tools/ must not import from tui/ (AGENTS.md dependency rules), so storage
locations used by cache, universe, workflow, and journal tools resolve here
instead of through TUI config. Tests override the root via the
QUANTAGENT_HOME environment variable.
"""
from __future__ import annotations

import os
from pathlib import Path


def quantagent_home() -> Path:
    """Return the QuantAgent home directory (default ``~/.quantagent``).

    Honors the ``QUANTAGENT_HOME`` environment variable when set.
    """
    override = os.environ.get("QUANTAGENT_HOME")
    return Path(override) if override else Path.home() / ".quantagent"


def cache_dir() -> Path:
    """Return the data cache directory."""
    return quantagent_home() / "cache"


def universes_dir() -> Path:
    """Return the custom universes directory."""
    return quantagent_home() / "universes"


def workflows_dir() -> Path:
    """Return the custom workflows directory."""
    return quantagent_home() / "workflows"


def trades_db_path() -> Path:
    """Return the trade journal SQLite database path."""
    return quantagent_home() / "trades.db"


def ensure_dir(path: Path) -> Path:
    """Create ``path`` (and parents) if missing and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path

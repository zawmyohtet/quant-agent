"""SQLite-backed session persistence."""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

logger = logging.getLogger(__name__)

DB_PATH = Path.home() / ".quantagent" / "sessions.db"


async def get_checkpointer() -> AsyncSqliteSaver:
    """Return an AsyncSqliteSaver checkpointer.

    Creates the database directory and connection if needed.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(str(DB_PATH))
    return AsyncSqliteSaver(conn)


def new_thread_id() -> str:
    """Generate a new thread ID."""
    import uuid_utils

    return str(uuid_utils.uuid7())


async def list_threads(db_path: Path = DB_PATH) -> list[dict]:
    """Return all stored threads ordered by creation time (newest first)."""
    if not db_path.exists():
        return []
    try:
        async with aiosqlite.connect(str(db_path)) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM threads ORDER BY created_at DESC") as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    except sqlite3.OperationalError:
        return []


async def delete_thread(thread_id: str, db_path: Path = DB_PATH) -> None:
    """Remove a thread from the database."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute("DELETE FROM threads WHERE id = ?", (thread_id,))
            await db.commit()
    except sqlite3.OperationalError:
        pass

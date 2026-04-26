from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import aiosqlite

from quantagent.tui.config import QuantAgentConfig

logger = logging.getLogger(__name__)

_DB_PATH = Path.home() / ".quantagent" / "sessions.db"


async def _init_db() -> None:
    """Ensure the sessions database has the required schema."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS threads (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                model TEXT,
                provider TEXT,
                first_message_preview TEXT
            )
            """
        )
        await db.commit()


@dataclass
class SessionState:
    """Mutable runtime state shared across the TUI and adapter."""

    config: QuantAgentConfig
    thread_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    token_count: int = 0
    is_running: bool = False
    pre_approve_next: bool = False

    def __post_init__(self) -> None:
        if self.config.thread_id:
            self.thread_id = self.config.thread_id

    def new_thread(self) -> None:
        """Generate a new thread ID and persist it."""
        self.thread_id = str(uuid.uuid4())
        self.token_count = 0
        self.config.thread_id = self.thread_id
        self.config.save()

    async def list_threads(self) -> list[dict]:
        """Return all stored threads ordered by creation time (newest first)."""
        await _init_db()
        async with aiosqlite.connect(_DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM threads ORDER BY created_at DESC") as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_thread(self, thread_id: str) -> dict | None:
        """Fetch a single thread by ID."""
        await _init_db()
        async with aiosqlite.connect(_DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def delete_thread(self, thread_id: str) -> None:
        """Remove a thread from the database."""
        await _init_db()
        async with aiosqlite.connect(_DB_PATH) as db:
            await db.execute("DELETE FROM threads WHERE id = ?", (thread_id,))
            await db.commit()

    async def upsert_thread(
        self,
        thread_id: str,
        created_at: str,
        model: str,
        provider: str,
        first_message_preview: str,
    ) -> None:
        """Insert or update a thread record."""
        await _init_db()
        async with aiosqlite.connect(_DB_PATH) as db:
            await db.execute(
                """
                INSERT INTO threads (id, created_at, model, provider, first_message_preview)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    created_at=excluded.created_at,
                    model=excluded.model,
                    provider=excluded.provider,
                    first_message_preview=excluded.first_message_preview
                """,
                (thread_id, created_at, model, provider, first_message_preview),
            )
            await db.commit()

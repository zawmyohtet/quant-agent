from __future__ import annotations

import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
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
    # What the agent is doing right now ("thinking" or a tool name); None when idle.
    current_activity: str | None = None
    # time.monotonic() when the current turn started; None when idle.
    turn_started_at: float | None = None

    def start_turn(self) -> None:
        self.is_running = True
        self.current_activity = "thinking"
        self.turn_started_at = time.monotonic()

    def end_turn(self) -> None:
        self.is_running = False
        self.current_activity = None
        self.turn_started_at = None

    def new_thread(self) -> None:
        """Generate a new thread ID and persist it."""
        self.thread_id = str(uuid.uuid4())
        self.token_count = 0
        self.config.thread_id = self.thread_id
        self.config.save()

    async def list_threads(self) -> list[dict]:
        """Return threads that actually have persisted messages, newest first.

        The checkpointer is the source of truth for which threads exist;
        metadata (preview/model/provider) is joined in for display so the
        list can never drift from where messages are stored.
        """
        await _init_db()
        async with aiosqlite.connect(_DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            try:
                async with db.execute(
                    """
                    SELECT c.thread_id AS id,
                           t.first_message_preview AS first_message_preview,
                           t.created_at AS created_at,
                           t.model AS model,
                           t.provider AS provider
                    FROM (SELECT DISTINCT thread_id FROM checkpoints) c
                    LEFT JOIN threads t ON t.id = c.thread_id
                    ORDER BY t.created_at DESC
                    """
                ) as cursor:
                    rows = await cursor.fetchall()
                    return [dict(row) for row in rows]
            except sqlite3.OperationalError:
                # No checkpoints table yet (fresh install).
                return []

    async def prune_empty_threads(self) -> None:
        """Drop metadata rows for threads that have no persisted messages."""
        await _init_db()
        async with aiosqlite.connect(_DB_PATH) as db:
            try:
                await db.execute(
                    "DELETE FROM threads WHERE id NOT IN "
                    "(SELECT DISTINCT thread_id FROM checkpoints)"
                )
                await db.commit()
            except sqlite3.OperationalError:
                pass

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

    async def note_user_message(self, text: str) -> None:
        """Record the first real user message as the thread's list preview.

        Only overwrites the placeholder preview so an existing thread's title
        is preserved on subsequent messages.
        """
        existing = await self.get_thread(self.thread_id)
        preview = existing.get("first_message_preview") if existing else None
        if preview not in (None, "", "Welcome"):
            return
        created_at = (existing or {}).get("created_at") or datetime.now(UTC).isoformat()
        await self.upsert_thread(
            thread_id=self.thread_id,
            created_at=created_at,
            model=self.config.model,
            provider=self.config.provider,
            first_message_preview=text[:80],
        )

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

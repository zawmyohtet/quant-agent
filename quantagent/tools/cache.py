"""Local data cache to reduce provider API calls.

SQLite-backed key-value store with per-entry TTL. Values are JSON documents;
pandas DataFrames are transparently encoded/decoded so OHLCV frames and
constituent lists can share one cache.
"""
from __future__ import annotations

import json
import time
from io import StringIO
from pathlib import Path
from typing import Any

import aiosqlite
import pandas as pd

from quantagent.tools._paths import cache_dir, ensure_dir

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    expires_at REAL NOT NULL
)
"""


def _encode(value: Any) -> str:
    """Encode a value as a JSON envelope (DataFrames get a dedicated kind)."""
    if isinstance(value, pd.DataFrame):
        return json.dumps(
            {"kind": "dataframe", "payload": value.to_json(orient="split", date_format="iso")}
        )
    return json.dumps({"kind": "json", "payload": value})


def _decode(raw: str) -> Any:
    """Decode a JSON envelope produced by :func:`_encode`."""
    envelope = json.loads(raw)
    if envelope["kind"] != "dataframe":
        return envelope["payload"]
    df = pd.read_json(StringIO(envelope["payload"]), orient="split")
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df


class DataCache:
    """Async key-value cache with TTL, stored in a local SQLite file.

    Default location: ``~/.quantagent/cache/datacache.db`` (see
    :mod:`quantagent.tools._paths` for overrides).
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path if db_path is not None else cache_dir() / "datacache.db"

    async def get(self, key: str) -> Any | None:
        """Return the cached value for ``key``, or None if missing/expired."""
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            value, expires_at = row
            if expires_at <= time.time():
                await db.execute("DELETE FROM cache WHERE key = ?", (key,))
                await db.commit()
                return None
            return _decode(value)

    async def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        """Store ``value`` under ``key`` for ``ttl`` seconds."""
        async with self._connect() as db:
            await db.execute(
                "INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
                (key, _encode(value), time.time() + ttl),
            )
            await db.commit()

    async def invalidate(self, key: str) -> None:
        """Remove ``key`` from the cache."""
        async with self._connect() as db:
            await db.execute("DELETE FROM cache WHERE key = ?", (key,))
            await db.commit()

    async def clear(self) -> None:
        """Remove all entries from the cache."""
        async with self._connect() as db:
            await db.execute("DELETE FROM cache")
            await db.commit()

    def _connect(self) -> _CacheConnection:
        """Open a connection with the schema applied."""
        ensure_dir(self._db_path.parent)
        return _CacheConnection(self._db_path)


class _CacheConnection:
    """Async context manager yielding an initialized aiosqlite connection."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def __aenter__(self) -> aiosqlite.Connection:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute(_SCHEMA)
        return self._db

    async def __aexit__(self, *exc_info: object) -> None:
        if self._db is not None:
            await self._db.close()

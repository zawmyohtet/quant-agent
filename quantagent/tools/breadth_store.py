"""Incremental SQLite store for universe-level breadth data.

Universe-wide breadth (A/D line, new highs/lows, percent above MA)
needs daily close/volume for hundreds of symbols. This store is warmed
once with ~1y of history via batch fetching, then kept fresh with
cheap incremental updates, so breadth tools never re-download the
whole universe.

Storage: ``~/.quantagent/cache/breadth.db``.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiosqlite
import pandas as pd

from quantagent.tools._paths import cache_dir, ensure_dir
from quantagent.tools.providers.base import AbstractDataProvider
from quantagent.tools.universe import load_universe
from quantagent.utils.progress import report_progress

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
    universe TEXT NOT NULL,
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    close REAL NOT NULL,
    volume REAL,
    PRIMARY KEY (universe, symbol, date)
);
CREATE TABLE IF NOT EXISTS universes (
    universe TEXT PRIMARY KEY,
    updated_at TEXT NOT NULL
);
"""

_WARM_CHUNK_SIZE = 100
_DEFAULT_MAX_AGE_DAYS = 3


class BreadthStore:
    """Incremental close/volume store keyed by (universe, symbol, date)."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path if db_path is not None else cache_dir() / "breadth.db"

    async def is_warm(self, universe: str, max_age_days: int = _DEFAULT_MAX_AGE_DAYS) -> bool:
        """True when the universe was ingested within ``max_age_days``."""
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT updated_at FROM universes WHERE universe = ?", (universe,)
            )
            row = await cursor.fetchone()
        if row is None:
            return False
        updated_at = datetime.fromisoformat(row[0])
        return datetime.now(UTC) - updated_at <= timedelta(days=max_age_days)

    async def ensure(
        self, provider: AbstractDataProvider, universe: str, allow_warmup: bool = True
    ) -> bool:
        """Make the universe usable; warm up or incrementally update as needed.

        Returns False when the store is cold and ``allow_warmup`` is False —
        callers should then fall back to a proxy computation.
        """
        if await self.is_warm(universe):
            return True
        if await self._has_data(universe):
            await self.update(provider, universe)
            return True
        if not allow_warmup:
            return False
        await self.warm_up(provider, universe)
        return True

    async def warm_up(
        self, provider: AbstractDataProvider, universe: str, period: str = "1y"
    ) -> dict:
        """Fetch ~1y of history for the whole universe and ingest it."""
        symbols = await asyncio.to_thread(load_universe, universe)
        if not symbols:
            raise ValueError(f"No symbols resolved for universe: {universe}")
        total_rows = 0
        fetched = 0
        for start in range(0, len(symbols), _WARM_CHUNK_SIZE):
            chunk = symbols[start : start + _WARM_CHUNK_SIZE]
            report_progress(
                f"warming {universe} breadth cache: "
                f"{start}/{len(symbols)} symbols…"
            )
            frames = await provider.get_batch_ohlcv(chunk, period=period)
            total_rows += await self._ingest(universe, frames)
            fetched += len(frames)
            logger.info(
                "Breadth warm-up %s: %d/%d symbols ingested",
                universe, min(start + _WARM_CHUNK_SIZE, len(symbols)), len(symbols),
            )
        report_progress(f"breadth cache for {universe} ready ({fetched} symbols)")
        await self._touch(universe)
        return {"universe": universe, "symbols": fetched, "rows": total_rows}

    async def update(self, provider: AbstractDataProvider, universe: str) -> dict:
        """Incrementally refresh recent bars for already-known symbols."""
        symbols = await self._known_symbols(universe)
        if not symbols:
            return await self.warm_up(provider, universe)
        frames = await provider.get_batch_ohlcv(symbols, period="5d")
        rows = await self._ingest(universe, frames)
        await self._touch(universe)
        return {"universe": universe, "symbols": len(frames), "rows": rows}

    async def load_field(
        self, universe: str, field: str = "close", days: int | None = None
    ) -> pd.DataFrame:
        """Load a wide matrix (index=date, columns=symbol) of close or volume."""
        _queries = {
            "close": "SELECT date, symbol, close FROM bars WHERE universe = ? ORDER BY date",
            "volume": "SELECT date, symbol, volume FROM bars WHERE universe = ? ORDER BY date",
        }
        query = _queries.get(field)
        if query is None:
            raise ValueError(f"Unknown field: {field}")
        async with self._connect() as db:
            cursor = await db.execute(query, (universe,))
            rows = await cursor.fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=["date", "symbol", field])
        matrix = df.pivot(index="date", columns="symbol", values=field)
        matrix.index = pd.DatetimeIndex(matrix.index, tz="UTC")
        return matrix.iloc[-days:] if days else matrix

    async def _ingest(self, universe: str, frames: dict[str, pd.DataFrame]) -> int:
        records = [
            (universe, sym, idx.date().isoformat(), float(close), float(volume))
            for sym, df in frames.items()
            for idx, close, volume in zip(df.index, df["Close"], df["Volume"], strict=False)
            if pd.notna(close)
        ]
        if not records:
            return 0
        async with self._connect() as db:
            await db.executemany(
                "INSERT OR REPLACE INTO bars (universe, symbol, date, close, volume) "
                "VALUES (?, ?, ?, ?, ?)",
                records,
            )
            await db.commit()
        return len(records)

    async def _touch(self, universe: str) -> None:
        async with self._connect() as db:
            await db.execute(
                "INSERT OR REPLACE INTO universes (universe, updated_at) VALUES (?, ?)",
                (universe, datetime.now(UTC).isoformat()),
            )
            await db.commit()

    async def _has_data(self, universe: str) -> bool:
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT 1 FROM bars WHERE universe = ? LIMIT 1", (universe,)
            )
            return await cursor.fetchone() is not None

    async def _known_symbols(self, universe: str) -> list[str]:
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT DISTINCT symbol FROM bars WHERE universe = ?", (universe,)
            )
            rows = await cursor.fetchall()
        return [r[0] for r in rows]

    def _connect(self) -> _StoreConnection:
        ensure_dir(self._db_path.parent)
        return _StoreConnection(self._db_path)


class _StoreConnection:
    """Async context manager yielding an initialized aiosqlite connection."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def __aenter__(self) -> aiosqlite.Connection:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.executescript(_SCHEMA)
        return self._db

    async def __aexit__(self, *exc_info: object) -> None:
        if self._db is not None:
            await self._db.close()

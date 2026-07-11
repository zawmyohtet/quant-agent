"""Trade journal with a forward-only lifecycle and MAE/MFE capture.

Trade ideas move strictly forward — idea → entry_ready → active →
partially_closed → closed (or invalidated from the pre-entry states) —
so history can't be retroactively rewritten. Closing a trade computes
the maximum adverse/favorable excursion (MAE/MFE) over the holding
period for postmortem quality analysis.

Storage: SQLite at ``~/.quantagent/trades.db``.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiosqlite
import pandas as pd
from pydantic import BaseModel, Field

from quantagent.tools._paths import ensure_dir, trades_db_path
from quantagent.tools.providers.base import AbstractDataProvider

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    thesis TEXT NOT NULL,
    entry_plan TEXT NOT NULL,
    target REAL,
    stop REAL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    entered_at TEXT,
    closed_at TEXT,
    entry_price REAL,
    exit_price REAL,
    realized_pnl_pct REAL,
    mae_pct REAL,
    mfe_pct REAL,
    outcome TEXT,
    notes TEXT NOT NULL DEFAULT '[]'
)
"""

# Forward-only lifecycle: no transition may move a trade backwards.
_TRANSITIONS: dict[str, set[str]] = {
    "idea": {"entry_ready", "invalidated"},
    "entry_ready": {"active", "invalidated"},
    "active": {"partially_closed", "closed"},
    "partially_closed": {"closed"},
    "closed": set(),
    "invalidated": set(),
}

OPEN_STATUSES = ("idea", "entry_ready", "active", "partially_closed")


class TradeIdea(BaseModel):
    """One journaled trade idea and its lifecycle state."""

    id: str
    symbol: str
    thesis: str
    entry_plan: str
    target: float | None = None
    stop: float | None = None
    status: str = "idea"
    created_at: datetime
    entered_at: datetime | None = None
    closed_at: datetime | None = None
    entry_price: float | None = None
    exit_price: float | None = None
    realized_pnl_pct: float | None = None
    mae_pct: float | None = None
    mfe_pct: float | None = None
    outcome: str | None = None
    notes: list[str] = Field(default_factory=list)


class _JournalConnection:
    """Async context manager yielding an initialized aiosqlite connection."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def __aenter__(self) -> aiosqlite.Connection:
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute(_SCHEMA)
        return self._db

    async def __aexit__(self, *exc_info: object) -> None:
        if self._db is not None:
            await self._db.close()


def _connect() -> _JournalConnection:
    path = trades_db_path()
    ensure_dir(path.parent)
    return _JournalConnection(path)


def _row_to_trade(row: aiosqlite.Row) -> TradeIdea:
    data = dict(row)
    data["notes"] = json.loads(data.get("notes") or "[]")
    return TradeIdea(**data)


async def _load_trade(db: aiosqlite.Connection, trade_id: str) -> TradeIdea:
    cursor = await db.execute("SELECT * FROM trades WHERE id = ?", (trade_id,))
    row = await cursor.fetchone()
    if row is None:
        raise ValueError(f"Unknown trade id: {trade_id}")
    return _row_to_trade(row)


def _require_transition(current: str, new: str) -> None:
    allowed = _TRANSITIONS.get(current, set())
    if new not in allowed:
        raise ValueError(
            f"Invalid transition {current} -> {new} (lifecycle is forward-only; "
            f"allowed from {current}: {sorted(allowed) or 'none'})"
        )


async def log_trade_idea(
    symbol: str,
    thesis: str,
    entry_plan: str,
    target: float | None = None,
    stop: float | None = None,
) -> TradeIdea:
    """Log a new trade idea to the journal (status: idea)."""
    trade = TradeIdea(
        id=uuid.uuid4().hex[:12],
        symbol=symbol.upper(),
        thesis=thesis,
        entry_plan=entry_plan,
        target=target,
        stop=stop,
        created_at=datetime.now(UTC),
    )
    async with _connect() as db:
        await db.execute(
            "INSERT INTO trades (id, symbol, thesis, entry_plan, target, stop, "
            "status, created_at, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                trade.id, trade.symbol, trade.thesis, trade.entry_plan,
                trade.target, trade.stop, trade.status,
                trade.created_at.isoformat(), "[]",
            ),
        )
        await db.commit()
    return trade


async def update_trade_status(
    trade_id: str,
    status: str,
    notes: str | None = None,
    entry_price: float | None = None,
) -> TradeIdea:
    """Advance a trade's status (forward-only) and optionally add a note.

    Moving to ``active`` records ``entered_at`` and requires
    ``entry_price`` so MAE/MFE and P&L can be computed at close.

    Raises:
        ValueError: On backward transitions or missing entry price.
    """
    async with _connect() as db:
        trade = await _load_trade(db, trade_id)
        _require_transition(trade.status, status)
        if status == "active" and entry_price is None:
            raise ValueError("entry_price is required when activating a trade")
        note_list = trade.notes + ([notes] if notes else [])
        entered_at = (
            datetime.now(UTC).isoformat()
            if status == "active"
            else trade.entered_at.isoformat() if trade.entered_at else None
        )
        closed_at = (
            datetime.now(UTC).isoformat()
            if status in ("closed", "invalidated")
            else None
        )
        await db.execute(
            "UPDATE trades SET status = ?, notes = ?, entry_price = COALESCE(?, "
            "entry_price), entered_at = ?, closed_at = COALESCE(?, closed_at) "
            "WHERE id = ?",
            (status, json.dumps(note_list), entry_price, entered_at, closed_at,
             trade_id),
        )
        await db.commit()
        return await _load_trade(db, trade_id)


async def close_trade(
    provider: AbstractDataProvider,
    trade_id: str,
    exit_price: float,
    outcome_notes: str | None = None,
) -> TradeIdea:
    """Close an active trade, recording P&L and MAE/MFE over the holding period.

    Raises:
        ValueError: When the trade is not in an active state.
    """
    async with _connect() as db:
        trade = await _load_trade(db, trade_id)
        _require_transition(trade.status, "closed")
        pnl = (
            round(exit_price / trade.entry_price - 1, 4)
            if trade.entry_price
            else None
        )
        mae, mfe = await _compute_excursions(provider, trade)
        outcome = "win" if pnl is not None and pnl > 0 else "loss"
        note_list = trade.notes + ([outcome_notes] if outcome_notes else [])
        await db.execute(
            "UPDATE trades SET status = 'closed', closed_at = ?, exit_price = ?, "
            "realized_pnl_pct = ?, mae_pct = ?, mfe_pct = ?, outcome = ?, "
            "notes = ? WHERE id = ?",
            (
                datetime.now(UTC).isoformat(), exit_price, pnl, mae, mfe,
                outcome, json.dumps(note_list), trade_id,
            ),
        )
        await db.commit()
        return await _load_trade(db, trade_id)


async def _compute_excursions(
    provider: AbstractDataProvider, trade: TradeIdea
) -> tuple[float | None, float | None]:
    """MAE/MFE (long-side) from OHLCV between entry and now."""
    if trade.entry_price is None or trade.entered_at is None:
        return None, None
    try:
        df = await provider.get_ohlcv(trade.symbol, period="1y")
    except Exception as exc:
        logger.warning("MAE/MFE unavailable for %s: %s", trade.symbol, exc)
        return None, None
    entered_day = pd.Timestamp(trade.entered_at).normalize()
    window = df[df.index >= entered_day]
    if window.empty:
        return None, None
    mae = round(float(window["Low"].min()) / trade.entry_price - 1, 4)
    mfe = round(float(window["High"].max()) / trade.entry_price - 1, 4)
    return mae, mfe


async def get_open_trades() -> list[TradeIdea]:
    """List all trades not yet closed or invalidated."""
    placeholders = ",".join("?" for _ in OPEN_STATUSES)
    async with _connect() as db:
        cursor = await db.execute(
            f"SELECT * FROM trades WHERE status IN ({placeholders}) "
            "ORDER BY created_at DESC",
            OPEN_STATUSES,
        )
        rows = await cursor.fetchall()
    return [_row_to_trade(r) for r in rows]


async def get_trade_history(
    days: int = 30,
    status: str | None = None,
) -> list[TradeIdea]:
    """List trades created within ``days``, optionally filtered by status."""
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    query = "SELECT * FROM trades WHERE created_at >= ?"
    params: list = [cutoff]
    if status is not None:
        query += " AND status = ?"
        params.append(status)
    async with _connect() as db:
        cursor = await db.execute(query + " ORDER BY created_at DESC", params)
        rows = await cursor.fetchall()
    return [_row_to_trade(r) for r in rows]


async def compute_trade_stats() -> dict:
    """Journal statistics over closed trades with recorded P&L."""
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT realized_pnl_pct, mae_pct, mfe_pct FROM trades "
            "WHERE status = 'closed' AND realized_pnl_pct IS NOT NULL "
            "ORDER BY closed_at"
        )
        rows = await cursor.fetchall()
    pnls = [float(r["realized_pnl_pct"]) for r in rows]
    if not pnls:
        return {"total_trades": 0}
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    maes = [float(r["mae_pct"]) for r in rows if r["mae_pct"] is not None]
    mfes = [float(r["mfe_pct"]) for r in rows if r["mfe_pct"] is not None]
    gross_loss = abs(sum(losses))
    return {
        "total_trades": len(pnls),
        "win_rate": round(len(wins) / len(pnls), 4),
        "avg_win": round(sum(wins) / len(wins), 4) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 4) if losses else 0.0,
        "profit_factor": (
            round(sum(wins) / gross_loss, 4) if gross_loss > 0 else None
        ),
        "expectancy": round(sum(pnls) / len(pnls), 4),
        "max_consecutive_losses": _max_consecutive_losses(pnls),
        "avg_mae": round(sum(maes) / len(maes), 4) if maes else None,
        "avg_mfe": round(sum(mfes) / len(mfes), 4) if mfes else None,
    }


def _max_consecutive_losses(pnls: list[float]) -> int:
    worst = current = 0
    for pnl in pnls:
        current = current + 1 if pnl <= 0 else 0
        worst = max(worst, current)
    return worst

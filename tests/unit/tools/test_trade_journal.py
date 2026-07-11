"""Tests for the trade journal."""
from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest
from _synthetic import SyntheticProvider, make_ohlcv

from quantagent.tools.trade_journal import (
    close_trade,
    compute_trade_stats,
    get_open_trades,
    get_trade_history,
    log_trade_idea,
    update_trade_status,
)


async def _logged_trade() -> str:
    trade = await log_trade_idea(
        "aapl", "Breakout above resistance", "Buy on volume confirmation",
        target=210.0, stop=185.0,
    )
    return trade.id


async def test_log_trade_idea_uppercases_and_defaults() -> None:
    trade = await log_trade_idea("nvda", "AI capex cycle", "Buy pullback to 50dma")
    assert trade.symbol == "NVDA"
    assert trade.status == "idea"
    assert trade.stop is None
    assert trade.notes == []


async def test_forward_lifecycle() -> None:
    trade_id = await _logged_trade()
    trade = await update_trade_status(trade_id, "entry_ready", notes="setup confirmed")
    assert trade.status == "entry_ready"
    assert trade.notes == ["setup confirmed"]
    trade = await update_trade_status(trade_id, "active", entry_price=190.0)
    assert trade.status == "active"
    assert trade.entry_price == 190.0
    assert trade.entered_at is not None


async def test_backward_transition_rejected() -> None:
    trade_id = await _logged_trade()
    await update_trade_status(trade_id, "entry_ready")
    with pytest.raises(ValueError):
        await update_trade_status(trade_id, "idea")


async def test_activation_requires_entry_price() -> None:
    trade_id = await _logged_trade()
    await update_trade_status(trade_id, "entry_ready")
    with pytest.raises(ValueError):
        await update_trade_status(trade_id, "active")


async def test_closed_trade_is_terminal() -> None:
    trade_id = await _logged_trade()
    await update_trade_status(trade_id, "entry_ready")
    await update_trade_status(trade_id, "active", entry_price=190.0)
    provider = SyntheticProvider({"AAPL": make_ohlcv(np.full(30, 195.0))})
    await close_trade(provider, trade_id, exit_price=200.0)
    with pytest.raises(ValueError):
        await update_trade_status(trade_id, "active", entry_price=1.0)


async def test_cannot_close_unentered_trade() -> None:
    trade_id = await _logged_trade()
    provider = SyntheticProvider({})
    with pytest.raises(ValueError):
        await close_trade(provider, trade_id, exit_price=200.0)


async def test_close_records_pnl_and_excursions() -> None:
    trade_id = await _logged_trade()
    await update_trade_status(trade_id, "entry_ready")
    await update_trade_status(trade_id, "active", entry_price=100.0)
    # Bars must fall inside the holding window (entry day onward).
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    # High 121.2, Low 89.1 over the holding window (make_ohlcv sets ±1%).
    provider = SyntheticProvider(
        {"AAPL": make_ohlcv([100.0, 90.0, 120.0, 110.0], start=today)}
    )
    trade = await close_trade(provider, trade_id, exit_price=110.0, outcome_notes="took profit")
    assert trade.status == "closed"
    assert trade.realized_pnl_pct == 0.1
    assert trade.outcome == "win"
    assert trade.mfe_pct == pytest.approx(0.212, abs=1e-3)
    assert trade.mae_pct == pytest.approx(-0.109, abs=1e-3)
    assert "took profit" in trade.notes


async def test_close_without_ohlcv_still_closes() -> None:
    trade_id = await _logged_trade()
    await update_trade_status(trade_id, "entry_ready")
    await update_trade_status(trade_id, "active", entry_price=100.0)
    trade = await close_trade(SyntheticProvider({}), trade_id, exit_price=95.0)
    assert trade.status == "closed"
    assert trade.outcome == "loss"
    assert trade.mae_pct is None


async def test_invalidate_idea() -> None:
    trade_id = await _logged_trade()
    trade = await update_trade_status(trade_id, "invalidated", notes="setup broke")
    assert trade.status == "invalidated"
    assert trade.closed_at is not None


async def test_open_trades_and_history_filters() -> None:
    open_id = await _logged_trade()
    invalid_id = await _logged_trade()
    await update_trade_status(invalid_id, "invalidated")
    open_ids = {t.id for t in await get_open_trades()}
    assert open_id in open_ids
    assert invalid_id not in open_ids
    invalidated = await get_trade_history(days=7, status="invalidated")
    assert {t.id for t in invalidated} == {invalid_id}


async def test_unknown_trade_id() -> None:
    with pytest.raises(ValueError):
        await update_trade_status("nope", "entry_ready")


async def _close_with_pnl(exit_price: float) -> None:
    trade_id = await _logged_trade()
    await update_trade_status(trade_id, "entry_ready")
    await update_trade_status(trade_id, "active", entry_price=100.0)
    provider = SyntheticProvider({"AAPL": make_ohlcv([100.0, exit_price])})
    await close_trade(provider, trade_id, exit_price=exit_price)


async def test_trade_stats() -> None:
    for exit_price in (110.0, 120.0, 95.0, 90.0, 85.0):
        await _close_with_pnl(exit_price)
    stats = await compute_trade_stats()
    assert stats["total_trades"] == 5
    assert stats["win_rate"] == 0.4
    assert stats["avg_win"] == pytest.approx(0.15)
    assert stats["avg_loss"] == pytest.approx(-0.1, abs=1e-3)
    assert stats["max_consecutive_losses"] == 3
    assert stats["profit_factor"] == pytest.approx(1.0, abs=0.01)


async def test_trade_stats_empty() -> None:
    assert (await compute_trade_stats())["total_trades"] == 0

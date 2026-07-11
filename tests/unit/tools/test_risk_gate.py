"""Tests for the risk-gating stack."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from _synthetic import SyntheticProvider, make_ohlcv, trend_close

from quantagent.tools.risk_gate import (
    CircuitBreakerConfig,
    check_circuit_breaker,
    check_discipline_gate,
)
from quantagent.tools.trade_journal import (
    close_trade,
    log_trade_idea,
    update_trade_status,
)
from quantagent.tools.universe import SECTOR_ETFS


async def _closed_trade(exit_price: float, symbol: str = "AAPL") -> None:
    trade = await log_trade_idea(symbol, "thesis", "plan", stop=90.0)
    await update_trade_status(trade.id, "entry_ready")
    await update_trade_status(trade.id, "active", entry_price=100.0)
    provider = SyntheticProvider({symbol: make_ohlcv([100.0, exit_price])})
    await close_trade(provider, trade.id, exit_price=exit_price)


async def test_breaker_allows_on_empty_journal() -> None:
    result = await check_circuit_breaker()
    assert result["state"] == "trading_allowed"
    assert result["triggered_rules"] == []


async def test_breaker_halts_on_daily_loss() -> None:
    await _closed_trade(97.0)  # -3% today > 2% daily limit
    result = await check_circuit_breaker()
    assert result["state"] == "halted"
    assert any("daily" in rule for rule in result["triggered_rules"])
    assert result["period_pnl"]["daily_pct"] == -3.0


async def test_breaker_cooldown_after_consecutive_losses() -> None:
    await _closed_trade(99.5)  # -0.5%
    await _closed_trade(99.5)  # -0.5%; total -1% < daily limit
    result = await check_circuit_breaker()
    assert result["state"] == "cooldown"
    assert result["cooldown_until"] is not None


async def test_breaker_wins_reset_streak() -> None:
    await _closed_trade(99.5)
    await _closed_trade(101.0)
    result = await check_circuit_breaker()
    assert result["state"] == "trading_allowed"


async def test_breaker_custom_config() -> None:
    await _closed_trade(99.0)  # -1%
    config = CircuitBreakerConfig(daily_loss_limit_pct=0.5)
    result = await check_circuit_breaker(config)
    assert result["state"] == "halted"


def _regime_frames(bullish: bool) -> dict[str, pd.DataFrame]:
    strong, weak = (0.002, -0.002) if bullish else (-0.002, 0.002)
    frames: dict[str, pd.DataFrame] = {
        "SPY": make_ohlcv(trend_close(drift=strong)),
        "RSP": make_ohlcv(trend_close(drift=strong * 1.5)),
        "IWM": make_ohlcv(trend_close(drift=strong * 1.5)),
        "XLY": make_ohlcv(trend_close(drift=strong * 1.5)),
        "XLP": make_ohlcv(trend_close(drift=weak)),
        "TLT": make_ohlcv(trend_close(drift=weak)),
        "HYG": make_ohlcv(trend_close(drift=strong)),
        "LQD": make_ohlcv(trend_close(drift=weak)),
        "^VIX": make_ohlcv(np.full(120, 12.0 if bullish else 38.0)),
    }
    for etf in SECTOR_ETFS.values():
        frames.setdefault(etf, make_ohlcv(trend_close(drift=strong)))
    return frames


async def test_discipline_gate_passes_clean_trade() -> None:
    trade = await log_trade_idea("AAPL", "solid thesis", "clear plan", stop=90.0)
    provider = SyntheticProvider(_regime_frames(bullish=True))
    result = await check_discipline_gate(provider, trade.id)
    assert result["result"] == "pass"
    assert all(c["passed"] for c in result["checks"].values())


async def test_discipline_gate_blocks_without_stop() -> None:
    trade = await log_trade_idea("AAPL", "thesis", "plan")  # no stop
    provider = SyntheticProvider(_regime_frames(bullish=True))
    result = await check_discipline_gate(provider, trade.id)
    assert result["result"] == "blocked"
    assert result["checks"]["stop_defined"]["passed"] is False


async def test_discipline_gate_blocks_in_bear_regime() -> None:
    trade = await log_trade_idea("AAPL", "thesis", "plan", stop=90.0)
    provider = SyntheticProvider(_regime_frames(bullish=False))
    result = await check_discipline_gate(provider, trade.id)
    assert result["result"] == "blocked"
    assert result["checks"]["market_regime"]["passed"] is False


async def test_discipline_gate_blocks_when_breaker_halted() -> None:
    await _closed_trade(95.0)  # -5% trips the daily limit
    trade = await log_trade_idea("MSFT", "thesis", "plan", stop=90.0)
    provider = SyntheticProvider(_regime_frames(bullish=True))
    result = await check_discipline_gate(provider, trade.id)
    assert result["result"] == "blocked"
    assert result["checks"]["circuit_breaker"]["passed"] is False


async def test_discipline_gate_unknown_trade() -> None:
    provider = SyntheticProvider(_regime_frames(bullish=True))
    with pytest.raises(ValueError):
        await check_discipline_gate(provider, "ghost")

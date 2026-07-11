"""Behavioral risk-gating stack: circuit breaker + pre-trade discipline gate.

Adapted from claude-trading-skills. Both gates emit *recommendations*
(they never touch a broker): the circuit breaker halts new entries
after account-level loss limits or losing streaks; the discipline gate
blocks entries that lack a written plan, a stop, or fight the regime.

P&L note: period P&L is approximated by summing per-trade realized
percentage returns from the journal — i.e. it assumes roughly
equal-sized positions. Good enough to trip behavioral guardrails; not
an accounting statement.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict

from quantagent.tools.market_breadth import detect_market_regime
from quantagent.tools.providers.base import AbstractDataProvider
from quantagent.tools.trade_journal import TradeIdea, get_trade_history

logger = logging.getLogger(__name__)

_REDUCE_ONLY_REGIMES = {"bear", "strong-bear"}


class CircuitBreakerConfig(BaseModel):
    """Loss limits and streak cooldown for the circuit breaker."""

    model_config = ConfigDict(frozen=True)
    daily_loss_limit_pct: float = 2.0
    weekly_loss_limit_pct: float = 5.0
    monthly_loss_limit_pct: float = 8.0
    consecutive_loss_cooldown: int = 2
    cooldown_hours: int = 24


def _period_pnl(trades: list[TradeIdea], since: datetime) -> float:
    return round(
        sum(
            t.realized_pnl_pct * 100
            for t in trades
            if t.realized_pnl_pct is not None
            and t.closed_at is not None
            and t.closed_at >= since
        ),
        4,
    )


def _consecutive_losses(trades: list[TradeIdea]) -> tuple[int, datetime | None]:
    """(current losing streak, close time of the most recent loss)."""
    closed = sorted(
        (t for t in trades if t.closed_at and t.realized_pnl_pct is not None),
        key=lambda t: t.closed_at or datetime.min.replace(tzinfo=UTC),
    )
    streak = 0
    last_loss_at: datetime | None = None
    for trade in closed:
        if trade.realized_pnl_pct is not None and trade.realized_pnl_pct <= 0:
            streak += 1
            last_loss_at = trade.closed_at
        else:
            streak = 0
            last_loss_at = None
    return streak, last_loss_at


async def check_circuit_breaker(
    config: CircuitBreakerConfig | None = None,
) -> dict:
    """Evaluate journal P&L against loss limits and losing streaks.

    Returns:
        Dict: {state: trading_allowed | cooldown | halted, triggered_rules,
        cooldown_until, period_pnl: {daily_pct, weekly_pct, monthly_pct}}.
        An empty journal defaults to trading_allowed.
    """
    config = config or CircuitBreakerConfig()
    now = datetime.now(UTC)
    trades = await get_trade_history(days=40, status="closed")
    period_pnl = {
        "daily_pct": _period_pnl(trades, now - timedelta(days=1)),
        "weekly_pct": _period_pnl(trades, now - timedelta(days=7)),
        "monthly_pct": _period_pnl(trades, now - timedelta(days=31)),
    }
    triggered = _triggered_rules(period_pnl, config)
    state = "halted" if triggered else "trading_allowed"
    cooldown_until = None
    if not triggered:
        streak, last_loss_at = _consecutive_losses(trades)
        if streak >= config.consecutive_loss_cooldown and last_loss_at is not None:
            until = last_loss_at + timedelta(hours=config.cooldown_hours)
            if until > now:
                state = "cooldown"
                cooldown_until = until.isoformat()
                triggered.append(
                    f"{streak} consecutive losses — cooldown for "
                    f"{config.cooldown_hours}h after the last loss"
                )
    return {
        "state": state,
        "triggered_rules": triggered,
        "cooldown_until": cooldown_until,
        "period_pnl": period_pnl,
    }


def _triggered_rules(period_pnl: dict, config: CircuitBreakerConfig) -> list[str]:
    limits = [
        ("daily_pct", config.daily_loss_limit_pct, "daily"),
        ("weekly_pct", config.weekly_loss_limit_pct, "weekly"),
        ("monthly_pct", config.monthly_loss_limit_pct, "monthly"),
    ]
    return [
        f"{label} loss {abs(period_pnl[key])}% exceeds {limit}% limit"
        for key, limit, label in limits
        if period_pnl[key] <= -limit
    ]


async def check_discipline_gate(
    provider: AbstractDataProvider,
    trade_id: str,
    config: CircuitBreakerConfig | None = None,
) -> dict:
    """Validate a journaled trade idea against discipline rules.

    Blocks when: the thesis or entry plan is missing, no stop is
    defined, the circuit breaker is in cooldown/halted state, or the
    market regime recommends reduce-only (bear/strong-bear).

    Args:
        provider: Market data provider (for the regime check).
        trade_id: Journal trade id to validate.
        config: Optional circuit-breaker overrides.

    Returns:
        Dict: {result: pass | blocked, checks: {name: {passed, detail}}}.
    """
    from quantagent.tools.trade_journal import _connect, _load_trade

    async with _connect() as db:
        trade = await _load_trade(db, trade_id)
    breaker = await check_circuit_breaker(config)
    regime = await detect_market_regime(provider)
    checks = {
        "written_thesis": _check(bool(trade.thesis.strip()), trade.thesis or "missing"),
        "entry_plan": _check(bool(trade.entry_plan.strip()), trade.entry_plan or "missing"),
        "stop_defined": _check(
            trade.stop is not None, f"stop={trade.stop}" if trade.stop else "no stop"
        ),
        "circuit_breaker": _check(
            breaker["state"] == "trading_allowed",
            f"state={breaker['state']}",
        ),
        "market_regime": _check(
            regime["regime"] not in _REDUCE_ONLY_REGIMES,
            f"regime={regime['regime']} "
            f"(exposure {regime['recommended_exposure']['min_pct']}-"
            f"{regime['recommended_exposure']['max_pct']}%)",
        ),
    }
    result = "pass" if all(c["passed"] for c in checks.values()) else "blocked"
    return {"result": result, "trade_id": trade_id, "checks": checks}


def _check(passed: bool, detail: str) -> dict:
    return {"passed": passed, "detail": detail}

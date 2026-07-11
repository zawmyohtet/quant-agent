"""Tests for earnings event analysis."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from _synthetic import SyntheticProvider, make_ohlcv

from quantagent.tools import screener
from quantagent.tools.event_analysis import (
    analyze_earnings_impact,
    get_earnings_calendar_range,
)


class EarningsProvider(SyntheticProvider):
    """Synthetic provider with earnings history and calendar support."""

    def __init__(
        self,
        frames: dict[str, pd.DataFrame],
        history: dict[str, list[dict]] | None = None,
        calendars: dict[str, list[dict]] | None = None,
    ) -> None:
        super().__init__(frames)
        self.history = history or {}
        self.calendars = calendars or {}
        self.calendar_calls = 0

    async def get_earnings_history(self, symbol: str, quarters: int = 8) -> list[dict]:
        return self.history.get(symbol, [])[:quarters]

    async def get_earnings_calendar(
        self, symbol: str, lookahead_days: int = 90
    ) -> list[dict]:
        self.calendar_calls += 1
        if symbol not in self.calendars:
            raise ValueError(f"no calendar for {symbol}")
        return self.calendars[symbol]


def _earnings_frame() -> tuple[pd.DataFrame, str, str]:
    """Flat series with a +5% jump at bar 60 and a -3% drop at bar 120.

    Returns the frame and the two event dates.
    """
    close = np.full(200, 100.0)
    close[60:] = 105.0
    close[120:] = 105.0 * 0.97
    df = make_ohlcv(close)
    # Open equals close in make_ohlcv, so gap == day1 move.
    return df, df.index[60].date().isoformat(), df.index[120].date().isoformat()


async def test_analyze_earnings_impact_events() -> None:
    df, up_date, down_date = _earnings_frame()
    provider = EarningsProvider(
        {"AAPL": df},
        history={
            "AAPL": [
                {"date": down_date, "eps_estimate": 1.0, "eps_actual": 0.9,
                 "surprise_pct": -10.0},
                {"date": up_date, "eps_estimate": 1.0, "eps_actual": 1.2,
                 "surprise_pct": 20.0},
            ]
        },
    )
    result = await analyze_earnings_impact(provider, "aapl")
    assert result["symbol"] == "AAPL"
    assert result["events_analyzed"] == 2
    moves = {e["date"]: e["day1_move"] for e in result["events"]}
    assert moves[up_date] == pytest.approx(0.05)
    assert moves[down_date] == pytest.approx(-0.03)
    assert result["positive_rate"] == 0.5
    assert result["avg_abs_day1_move"] == pytest.approx(0.04)
    # Prices are flat after each event -> zero drift.
    assert result["avg_drift_5d"] == pytest.approx(0.0)


async def test_analyze_earnings_impact_no_history() -> None:
    provider = EarningsProvider({"AAPL": make_ohlcv([100.0] * 50)})
    result = await analyze_earnings_impact(provider, "AAPL")
    assert result["events_analyzed"] == 0
    assert result["events"] == []


async def test_event_outside_price_history_skipped() -> None:
    df, up_date, _ = _earnings_frame()
    provider = EarningsProvider(
        {"AAPL": df},
        history={"AAPL": [{"date": "2001-01-01", "eps_estimate": None,
                           "eps_actual": None, "surprise_pct": None}]},
    )
    result = await analyze_earnings_impact(provider, "AAPL")
    assert result["events_analyzed"] == 0


async def test_drift_none_when_insufficient_forward_bars() -> None:
    df, _, _ = _earnings_frame()
    last_date = df.index[-2].date().isoformat()
    provider = EarningsProvider(
        {"AAPL": df},
        history={"AAPL": [{"date": last_date, "eps_estimate": None,
                           "eps_actual": None, "surprise_pct": None}]},
    )
    result = await analyze_earnings_impact(provider, "AAPL")
    assert result["events_analyzed"] == 1
    assert result["events"][0]["drift_5d"] is None
    assert result["avg_drift_5d"] is None


def _calendar_provider() -> EarningsProvider:
    return EarningsProvider(
        {},
        calendars={
            "AAA": [{"symbol": "AAA", "date": "2026-07-20T10:00:00+00:00",
                     "eps_estimate": 1.5, "eps_actual": None, "quarter": "Q3-2026"}],
            "BBB": [{"symbol": "BBB", "date": "2026-09-01T10:00:00+00:00",
                     "eps_estimate": 2.0, "eps_actual": None, "quarter": "Q3-2026"}],
        },
    )


async def test_calendar_range_filters_dates() -> None:
    provider = _calendar_provider()
    df = await get_earnings_calendar_range(
        provider, "2026-07-13", "2026-07-31", symbols=["AAA", "BBB"]
    )
    assert df["symbol"].tolist() == ["AAA"]
    assert df.iloc[0]["date"] == "2026-07-20"


async def test_calendar_range_uses_cache() -> None:
    provider = _calendar_provider()
    await get_earnings_calendar_range(
        provider, "2026-07-13", "2026-12-31", symbols=["AAA", "BBB"]
    )
    first_calls = provider.calendar_calls
    df = await get_earnings_calendar_range(
        provider, "2026-07-13", "2026-12-31", symbols=["AAA", "BBB"]
    )
    assert provider.calendar_calls == first_calls  # served from cache
    assert len(df) == 2


async def test_calendar_range_skips_failing_symbols() -> None:
    provider = _calendar_provider()
    df = await get_earnings_calendar_range(
        provider, "2026-01-01", "2026-12-31", symbols=["AAA", "MISSING"]
    )
    assert df["symbol"].tolist() == ["AAA"]


async def test_calendar_range_universe_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(screener, "_fetch_universe_tickers", lambda universe: ["AAA"])
    df = await get_earnings_calendar_range(_calendar_provider(), "2026-01-01", "2026-12-31")
    assert df["symbol"].tolist() == ["AAA"]


async def test_calendar_range_empty() -> None:
    df = await get_earnings_calendar_range(
        _calendar_provider(), "2030-01-01", "2030-12-31", symbols=["AAA"]
    )
    assert df.empty

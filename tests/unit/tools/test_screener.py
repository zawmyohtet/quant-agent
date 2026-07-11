"""Tests for the stock screener."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from _synthetic import make_ohlcv, trend_close

from quantagent.tools import screener
from quantagent.tools.providers.base import AbstractDataProvider

_FUNDAMENTALS = {
    "AAA": {"name": "Alpha", "pe_ratio": 10.0, "pb_ratio": 1.5, "roe": 0.25,
            "roa": 0.10, "debt_equity": 0.5, "dividend_yield": 0.02,
            "revenue_growth": 0.15, "eps_growth": 0.20, "beta": 0.9},
    "BBB": {"name": "Beta", "pe_ratio": 30.0, "pb_ratio": 5.0, "roe": 0.05,
            "roa": 0.02, "debt_equity": 2.0, "dividend_yield": 0.0,
            "revenue_growth": 0.02, "eps_growth": -0.05, "beta": 1.5},
    "CCC": {"name": "Gamma", "pe_ratio": 18.0, "pb_ratio": 2.5, "roe": 0.15,
            "roa": 0.07, "debt_equity": 1.0, "dividend_yield": 0.01,
            "revenue_growth": 0.08, "eps_growth": 0.10, "beta": 1.1},
}

_QUOTES = {
    "AAA": {"price": 50.0, "volume": 2_000_000, "market_cap": 5e9},
    "BBB": {"price": 200.0, "volume": 8_000_000, "market_cap": 50e9},
    "CCC": {"price": 120.0, "volume": 4_000_000, "market_cap": 20e9},
}


class MockProvider(AbstractDataProvider):
    """Deterministic provider for screener tests."""

    def __init__(
        self,
        failing: set[str] | None = None,
        frames: dict[str, pd.DataFrame] | None = None,
    ) -> None:
        self.failing = failing or set()
        self.frames = frames or {}

    async def get_ohlcv(
        self, symbol: str, period: str = "1y", interval: str = "1d"
    ) -> pd.DataFrame:
        if symbol not in self.frames:
            raise ValueError(f"No data for {symbol}")
        return self.frames[symbol]

    async def get_quote(self, symbol: str) -> dict:
        if symbol in self.failing:
            raise ValueError(f"no quote for {symbol}")
        return {"symbol": symbol, **_QUOTES[symbol]}

    async def get_fundamentals(self, symbol: str) -> dict:
        if symbol in self.failing:
            raise ValueError(f"no fundamentals for {symbol}")
        return {"symbol": symbol, **_FUNDAMENTALS[symbol]}

    async def search_symbols(self, query: str) -> list[dict]:
        return []

    async def get_news(self, symbol: str, days: int = 7) -> list[dict]:
        return []

    async def get_earnings_calendar(
        self, symbol: str, lookahead_days: int = 90
    ) -> list[dict]:
        return []

    async def get_sector_performance(self) -> dict:
        return {}

    async def get_economic_indicators(self) -> dict:
        return {}


@pytest.fixture
def patched_universe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        screener, "_fetch_universe_tickers", lambda universe: ["AAA", "BBB", "CCC"]
    )


# ── Fundamental screening ────────────────────────────────────────────────────


async def test_screen_stocks_no_criteria(patched_universe: None) -> None:
    df = await screener.screen_stocks(MockProvider())
    assert len(df) == 3
    assert df["symbol"].tolist() == ["BBB", "CCC", "AAA"]


async def test_screen_stocks_applies_criteria(patched_universe: None) -> None:
    df = await screener.screen_stocks(MockProvider(), criteria={"pe_lt": 20, "roe_gt": 0.10})
    assert df["symbol"].tolist() == ["CCC", "AAA"]


async def test_screen_stocks_market_cap_alias(patched_universe: None) -> None:
    df = await screener.screen_stocks(MockProvider(), criteria={"market_cap_gt": 10e9})
    assert sorted(df["symbol"]) == ["BBB", "CCC"]


async def test_screen_stocks_unknown_criteria_ignored(patched_universe: None) -> None:
    df = await screener.screen_stocks(MockProvider(), criteria={"nonsense_gt": 1})
    assert len(df) == 3


async def test_screen_stocks_limit_and_sort(patched_universe: None) -> None:
    df = await screener.screen_stocks(
        MockProvider(), sort_by="pe_ratio", ascending=True, limit=1
    )
    assert df["symbol"].tolist() == ["AAA"]


async def test_screen_stocks_max_symbols(patched_universe: None) -> None:
    df = await screener.screen_stocks(MockProvider(), max_symbols=2)
    assert sorted(df["symbol"]) == ["AAA", "BBB"]


async def test_screen_stocks_skips_failing_tickers(patched_universe: None) -> None:
    df = await screener.screen_stocks(MockProvider(failing={"BBB"}))
    assert sorted(df["symbol"].tolist()) == ["AAA", "CCC"]


async def test_screen_stocks_all_tickers_fail(patched_universe: None) -> None:
    df = await screener.screen_stocks(MockProvider(failing={"AAA", "BBB", "CCC"}))
    assert df.empty


async def test_screen_stocks_unknown_universe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(screener, "_fetch_universe_tickers", lambda universe: [])
    df = await screener.screen_stocks(MockProvider(), universe="unknown")
    assert df.empty


async def test_screen_by_fundamentals(patched_universe: None) -> None:
    df = await screener.screen_by_fundamentals(MockProvider(), {"pb_gt": 2.0})
    assert sorted(df["symbol"]) == ["BBB", "CCC"]


async def test_screen_stocks_bad_criteria_value_ignored(patched_universe: None) -> None:
    df = await screener.screen_stocks(MockProvider(), criteria={"pe_lt": {"bad": "value"}})
    assert len(df) == 3


# ── Technical screening ──────────────────────────────────────────────────────


def _tech_frames() -> dict[str, pd.DataFrame]:
    momo_volume = np.full(300, 1_000_000.0)
    momo_volume[-1] = 3_000_000.0
    return {
        "MOMO": make_ohlcv(trend_close(n=300, drift=0.003), momo_volume),
        "WEAK": make_ohlcv(trend_close(n=300, drift=-0.003)),
    }


@pytest.fixture
def tech_provider(monkeypatch: pytest.MonkeyPatch) -> MockProvider:
    monkeypatch.setattr(
        screener, "_fetch_universe_tickers", lambda universe: ["MOMO", "WEAK"]
    )
    return MockProvider(frames=_tech_frames())


async def test_screen_technicals_rsi(tech_provider: MockProvider) -> None:
    df = await screener.screen_by_technicals(tech_provider, {"rsi_lt": 40})
    assert df["symbol"].tolist() == ["WEAK"]
    df = await screener.screen_by_technicals(tech_provider, {"rsi_gt": 60})
    assert df["symbol"].tolist() == ["MOMO"]


async def test_screen_technicals_trend(tech_provider: MockProvider) -> None:
    df = await screener.screen_by_technicals(
        tech_provider, {"price_above_sma": 200, "macd_bullish": True}
    )
    assert df["symbol"].tolist() == ["MOMO"]
    df = await screener.screen_by_technicals(tech_provider, {"price_below_sma": 200})
    assert df["symbol"].tolist() == ["WEAK"]


async def test_screen_technicals_volume_expansion(tech_provider: MockProvider) -> None:
    df = await screener.screen_by_technicals(tech_provider, {"volume_expansion": 2.0})
    assert df["symbol"].tolist() == ["MOMO"]


async def test_screen_technicals_adx(tech_provider: MockProvider) -> None:
    df = await screener.screen_by_technicals(tech_provider, {"adx_gt": 10})
    assert "MOMO" in df["symbol"].tolist()


async def test_screen_technicals_explicit_symbols(tech_provider: MockProvider) -> None:
    df = await screener.screen_by_technicals(
        tech_provider, {"rsi_gt": 0}, symbols=["MOMO"]
    )
    assert df["symbol"].tolist() == ["MOMO"]


def test_check_technical_unknown_key_passes() -> None:
    df = make_ohlcv(trend_close(n=50))
    assert screener._check_technical(df, "bogus_criterion", 1) is True


# ── Combined screening ───────────────────────────────────────────────────────


async def test_screen_combined_intersection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        screener, "_fetch_universe_tickers", lambda universe: ["AAA", "BBB", "CCC"]
    )
    frames = {
        "AAA": make_ohlcv(trend_close(n=300, drift=0.003)),
        "BBB": make_ohlcv(trend_close(n=300, drift=0.003)),
        "CCC": make_ohlcv(trend_close(n=300, drift=-0.003)),
    }
    provider = MockProvider(frames=frames)
    df = await screener.screen_combined(
        provider,
        technical_criteria={"price_above_sma": 200},
        fundamental_criteria={"pe_lt": 20},
        universe="sp500",
    )
    # pe_lt 20 keeps AAA + CCC; above-200SMA keeps AAA + BBB → intersection AAA.
    assert df["symbol"].tolist() == ["AAA"]
    assert "rsi" in df.columns


async def test_screen_combined_fundamentals_only(patched_universe: None) -> None:
    df = await screener.screen_combined(
        MockProvider(), fundamental_criteria={"pe_lt": 20}
    )
    assert sorted(df["symbol"]) == ["AAA", "CCC"]


async def test_screen_combined_empty_fundamentals(patched_universe: None) -> None:
    df = await screener.screen_combined(
        MockProvider(), fundamental_criteria={"pe_lt": 1},
        technical_criteria={"rsi_lt": 100},
    )
    assert df.empty


# ── Pattern screens ──────────────────────────────────────────────────────────


def _vcp_close() -> list[float]:
    """Advance 100->220, pull back to ~205, then tighten."""
    advance = list(np.linspace(100, 220, 237))
    pullback = list(np.linspace(220, 205, 13))
    tighten = [205 + 2 * np.sin(i / 3) * (1 - i / 50) for i in range(50)]
    return advance + pullback + tighten


def _vcp_frames() -> dict[str, pd.DataFrame]:
    volume = np.full(300, 1_000_000.0)
    volume[-10:] = 400_000.0
    return {
        "VCP": make_ohlcv(_vcp_close(), volume),
        "DOWN": make_ohlcv(trend_close(n=300, drift=-0.003)),
    }


async def test_screen_vcp_pattern(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        screener, "_fetch_universe_tickers", lambda universe: ["VCP", "DOWN"]
    )
    provider = MockProvider(frames=_vcp_frames())
    df = await screener.screen_vcp_pattern(provider)
    assert df["symbol"].tolist() == ["VCP"]
    row = df.iloc[0]
    assert row["prior_advance_pct"] >= 0.30
    assert row["contraction_pct"] <= 0.50
    assert row["volume_dryup_ratio"] < 1.0


async def test_screen_breakout_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        screener, "_fetch_universe_tickers", lambda universe: ["BRK", "DOWN"]
    )
    volume = np.full(300, 1_000_000.0)
    volume[-1] = 2_500_000.0
    frames = {
        "BRK": make_ohlcv(trend_close(n=300, drift=0.002), volume),
        "DOWN": make_ohlcv(trend_close(n=300, drift=-0.003)),
    }
    df = await screener.screen_breakout_candidates(MockProvider(frames=frames))
    assert df["symbol"].tolist() == ["BRK"]
    assert df.iloc[0]["pct_from_high"] <= 0.05
    assert df.iloc[0]["volume_ratio"] >= 1.5


def _oversold_close() -> list[float]:
    rise = list(np.linspace(100, 130, 150))
    fall = list(np.linspace(130, 94.5, 148))
    return rise + fall + [94.5, 95.4]


async def test_screen_oversold_reversal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        screener, "_fetch_universe_tickers", lambda universe: ["OSLD", "MOMO"]
    )
    frames = {
        "OSLD": make_ohlcv(_oversold_close()),
        "MOMO": make_ohlcv(trend_close(n=300, drift=0.003)),
    }
    df = await screener.screen_oversold_reversal(MockProvider(frames=frames))
    assert df["symbol"].tolist() == ["OSLD"]
    assert df.iloc[0]["rsi"] < 30
    assert df.iloc[0]["decline_pct"] >= 0.20

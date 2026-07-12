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


async def test_screen_stocks_sort_by_missing_field(patched_universe: None) -> None:
    df = await screener.screen_stocks(MockProvider(), sort_by="nonexistent")
    assert len(df) == 3


def tech_frames() -> dict[str, pd.DataFrame]:
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
    return MockProvider(frames=tech_frames())


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


async def test_screen_technicals_no_tickers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(screener, "_fetch_universe_tickers", lambda universe: [])
    df = await screener.screen_by_technicals(MockProvider(), {"rsi_lt": 30})
    assert df.empty


def test_check_technical_unknown_key_passes() -> None:
    df = make_ohlcv(trend_close(n=50))
    assert screener._check_technical(df, "bogus_criterion", 1) is True


def test_check_technical_atr_breakout() -> None:
    df = make_ohlcv(trend_close(n=50))
    result = screener._check_technical(df, "atr_breakout", True)
    assert result is not None


def test_check_technical_adx_gt() -> None:
    rng = np.random.default_rng(42)
    n = 100
    dates = pd.date_range("2023-06-01", periods=n, freq="D", tz="UTC")
    close = 100.0 + np.cumsum(rng.normal(0.001, 0.02, n))
    df = pd.DataFrame({
        "Open": close * (1 + rng.uniform(-0.01, 0.01, n)),
        "High": close * (1 + rng.uniform(0.01, 0.03, n)),
        "Low": close * (1 - rng.uniform(0.01, 0.03, n)),
        "Close": close,
        "Volume": rng.integers(1_000_000, 5_000_000, n),
    }, index=dates)
    result = screener._check_technical(df, "adx_gt", 10)
    assert result is not None


def test_sma_insufficient_data() -> None:
    assert screener._sma(pd.Series([100.0, 101.0]), 20) is None


def test_macd_bullish_insufficient_data() -> None:
    assert screener._macd_bullish(pd.Series([100.0] * 10)) is None


def test_volume_ratio_insufficient_data() -> None:
    assert screener._volume_ratio(pd.Series([1_000_000] * 5)) is None


def test_volume_ratio_zero_avg() -> None:
    assert screener._volume_ratio(pd.Series([0.0] * 25)) is None


def test_above_upper_band_insufficient_data() -> None:
    assert screener._above_upper_band(pd.Series([100.0] * 5)) is None


def test_adx_insufficient_data() -> None:
    df = make_ohlcv(trend_close(n=10))
    assert screener._adx(df) is None


def test_check_price_vs_sma_insufficient_data() -> None:
    close = pd.Series([100.0] * 10)
    assert screener._check_price_vs_sma(close, 20, above=True) is None


def test_apply_single_criterion_unknown_key() -> None:
    df = pd.DataFrame({"symbol": ["A"], "pe_ratio": [10.0]})
    result = screener._apply_single_criterion(df, "unknown_key", 1)
    assert len(result) == 1


def test_apply_single_criterion_exception() -> None:
    df = pd.DataFrame({"symbol": ["A"], "pe_ratio": [10.0]})
    result = screener._apply_single_criterion(df, "pe_lt", "not_a_number")
    assert len(result) == 1


def test_vcp_metrics_insufficient_data() -> None:
    df = make_ohlcv(trend_close(n=50))
    result = screener._vcp_metrics(df, max_contraction_pct=0.5, min_prior_advance_pct=0.3)
    assert result is None


def test_vcp_metrics_no_prior_advance() -> None:
    df = make_ohlcv(trend_close(n=250, drift=0.0))
    result = screener._vcp_metrics(df, max_contraction_pct=0.5, min_prior_advance_pct=0.3)
    assert result is None


def test_vcp_metrics_below_sma200() -> None:
    close = trend_close(n=300, drift=-0.0005)
    df = make_ohlcv(close)
    result = screener._vcp_metrics(df, max_contraction_pct=0.5, min_prior_advance_pct=0.0)
    assert result is None


def test_oversold_row_insufficient_data() -> None:
    df = make_ohlcv(trend_close(n=10))
    result = screener._oversold_row("TEST", df, rsi_threshold=30.0, min_decline_pct=0.2)
    assert result is None


def test_oversold_row_no_decline() -> None:
    close = trend_close(n=200, drift=0.002)
    df = make_ohlcv(close)
    result = screener._oversold_row("TEST", df, rsi_threshold=30.0, min_decline_pct=0.2)
    assert result is None


def test_technical_row_none_indicators() -> None:
    df = make_ohlcv(trend_close(n=5))
    row = screener._technical_row("TEST", df)
    assert row["symbol"] == "TEST"
    assert row["volume_ratio"] is None


def test_fetch_universe_tickers_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        screener, "load_universe", lambda universe: (_ for _ in ()).throw(ValueError("boom"))
    )
    result = screener._fetch_universe_tickers("bad")
    assert result == []


def test_vcp_metrics_negative_contraction() -> None:
    close = trend_close(n=300, drift=0.001)
    df = make_ohlcv(close)
    result = screener._vcp_metrics(df, max_contraction_pct=0.0, min_prior_advance_pct=0.0)
    if result is not None:
        assert result["contraction_pct"] >= 0


async def test_combined_empty_technical_criteria(patched_universe: None) -> None:
    df = await screener.screen_combined(
        MockProvider(),
        technical_criteria=None,
        fundamental_criteria={"pe_lt": 20},
    )
    assert len(df) == 2  # AAA + CCC

async def test_screen_combined_empty_fundamentals_no_tech(patched_universe: None) -> None:
    df = await screener.screen_combined(
        MockProvider(),
        fundamental_criteria={"pe_lt": 1},
        technical_criteria=None,
    )
    assert df.empty


async def test_breakout_empty_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        screener, "_fetch_universe_tickers", lambda universe: []
    )
    df = await screener.screen_breakout_candidates(MockProvider(), limit=10)
    assert df.empty


async def test_oversold_empty_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        screener, "_fetch_universe_tickers", lambda universe: []
    )
    df = await screener.screen_oversold_reversal(MockProvider(), limit=10)
    assert df.empty

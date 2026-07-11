"""Tests for the stock screener."""
from __future__ import annotations

import pandas as pd
import pytest

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

    def __init__(self, failing: set[str] | None = None) -> None:
        self.failing = failing or set()

    async def get_ohlcv(
        self, symbol: str, period: str = "1y", interval: str = "1d"
    ) -> pd.DataFrame:
        raise NotImplementedError

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
    # Default sort: market_cap descending
    assert df["symbol"].tolist() == ["BBB", "CCC", "AAA"]


async def test_screen_stocks_applies_criteria(patched_universe: None) -> None:
    df = await screener.screen_stocks(MockProvider(), criteria={"pe_lt": 20, "roe_gt": 0.10})
    assert df["symbol"].tolist() == ["CCC", "AAA"]


async def test_screen_stocks_unknown_criteria_ignored(patched_universe: None) -> None:
    df = await screener.screen_stocks(MockProvider(), criteria={"nonsense_gt": 1})
    assert len(df) == 3


async def test_screen_stocks_limit_and_sort(patched_universe: None) -> None:
    df = await screener.screen_stocks(
        MockProvider(), sort_by="pe_ratio", ascending=True, limit=1
    )
    assert df["symbol"].tolist() == ["AAA"]


async def test_screen_stocks_skips_failing_tickers(patched_universe: None) -> None:
    df = await screener.screen_stocks(MockProvider(failing={"BBB"}))
    assert sorted(df["symbol"].tolist()) == ["AAA", "CCC"]


async def test_screen_stocks_unknown_universe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(screener, "_fetch_universe_tickers", lambda universe: [])
    df = await screener.screen_stocks(MockProvider(), universe="unknown")
    assert df.empty


async def test_screen_stocks_all_tickers_fail(patched_universe: None) -> None:
    df = await screener.screen_stocks(MockProvider(failing={"AAA", "BBB", "CCC"}))
    assert df.empty


async def test_screen_stocks_bad_criteria_value_ignored(patched_universe: None) -> None:
    df = await screener.screen_stocks(MockProvider(), criteria={"pe_lt": {"bad": "value"}})
    assert len(df) == 3


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


def test_fetch_universe_tickers_success(monkeypatch: pytest.MonkeyPatch) -> None:
    html = (
        "<table><thead><tr><th>Symbol</th><th>Security</th></tr></thead>"
        "<tbody><tr><td>AAPL</td><td>Apple</td></tr>"
        "<tr><td>MSFT</td><td>Microsoft</td></tr></tbody></table>"
    )
    monkeypatch.setattr(
        screener.requests, "get", lambda url, headers, timeout: _FakeResponse(html)
    )
    assert screener._fetch_universe_tickers("sp500") == ["AAPL", "MSFT"]


def test_fetch_universe_tickers_unknown() -> None:
    assert screener._fetch_universe_tickers("bogus") == []


def test_fetch_universe_tickers_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(url: str, headers: dict, timeout: int) -> _FakeResponse:
        raise ConnectionError("offline")

    monkeypatch.setattr(screener.requests, "get", _boom)
    assert screener._fetch_universe_tickers("sp500") == []


def test_find_sp500_tickers_extracts_symbol_column() -> None:
    tables = [pd.DataFrame({"Symbol": ["AAPL", "MSFT"], "Security": ["Apple", "Microsoft"]})]
    assert screener._find_sp500_tickers(tables) == ["AAPL", "MSFT"]


def test_find_nasdaq100_tickers_scans_tables() -> None:
    tables = [
        pd.DataFrame({"Irrelevant": [1, 2]}),
        pd.DataFrame({"Ticker": ["NVDA", "AMD"]}),
    ]
    assert screener._find_nasdaq100_tickers(tables) == ["NVDA", "AMD"]

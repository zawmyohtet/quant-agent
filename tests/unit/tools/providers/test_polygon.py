"""Tests for Polygon.io provider."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from quantagent.tools.providers.polygon import (
    PolygonProvider,
    _build_news_entry,
    _interval_multiplier,
    _interval_to_timespan,
    _parse_news_timestamp,
    _pct,
    _period_to_start,
    _ytd,
)


class _MockAgg:
    def __init__(self) -> None:
        self.timestamp = int(datetime(2024, 6, 15, tzinfo=UTC).timestamp() * 1000)
        self.open = 100.0
        self.high = 101.0
        self.low = 99.0
        self.close = 100.5
        self.volume = 1_000_000


class _MockQuote:
    def __init__(self) -> None:
        self.last_price = 100.5
        self.bid_price = 100.0
        self.ask_price = 101.0


class _MockDetails:
    def __init__(self) -> None:
        self.market_cap = 2_000_000_000_000
        self.share_class_shares_outstanding = 15_000_000_000
        self.total_employees = 150_000
        self.sic_description = "Technology"


class _MockNewsItem:
    def __init__(self) -> None:
        self.title = "AAPL news"
        self.article_url = "https://example.com"
        self.published_utc = "2026-07-12T12:00:00Z"
        self.publisher = _MockPublisher()


class _MockPublisher:
    name = "Reuters"


class _MockTicker:
    def __init__(self) -> None:
        self.ticker = "AAPL"
        self.name = "Apple Inc"
        self.primary_exchange = "NASDAQ"


class _MockEarningsItem:
    def __init__(self) -> None:
        self.report_date = "2026-08-15"
        self.estimated_eps = 2.0
        self.reported_eps = 2.1
        self.fiscal_period = "Q3 2026"


def _make_mock_client() -> MagicMock:
    client = MagicMock()
    client.get_aggs.return_value = [_MockAgg()]
    client.get_last_quote.return_value = _MockQuote()
    client.get_ticker_details.return_value = _MockDetails()
    client.list_tickers.return_value = [_MockTicker()]
    client.list_ticker_news.return_value = [_MockNewsItem()]
    client.get_earnings_calendar.return_value = [_MockEarningsItem()]
    return client


@pytest.fixture
def polygon_provider() -> PolygonProvider:
    with patch("quantagent.tools.providers.polygon.RESTClient", return_value=_make_mock_client()):
        return PolygonProvider(api_key="test_key")


async def test_get_ohlcv(polygon_provider: PolygonProvider) -> None:
    with patch("quantagent.tools.providers.polygon.asyncio.to_thread", new_callable=AsyncMock) as mock_tt:
        mock_tt.return_value = [_MockAgg()]
        df = await polygon_provider.get_ohlcv("AAPL")
        assert "Close" in df.columns
        assert float(df["Close"].iloc[-1]) == 100.5


async def test_get_ohlcv_empty_raises(polygon_provider: PolygonProvider) -> None:
    with patch("quantagent.tools.providers.polygon.asyncio.to_thread", new_callable=AsyncMock) as mock_tt:
        mock_tt.return_value = []
        with pytest.raises(ValueError, match="No OHLCV data"):
            await polygon_provider.get_ohlcv("AAPL")


async def test_get_quote(polygon_provider: PolygonProvider) -> None:
    with patch("quantagent.tools.providers.polygon.asyncio.to_thread", new_callable=AsyncMock) as mock_tt:
        mock_tt.return_value = _MockQuote()
        result = await polygon_provider.get_quote("AAPL")
        assert result["symbol"] == "AAPL"
        assert result["price"] == 100.5
        assert result["bid"] == 100.0
        assert result["ask"] == 101.0


async def test_get_fundamentals(polygon_provider: PolygonProvider) -> None:
    with patch("quantagent.tools.providers.polygon.asyncio.to_thread", new_callable=AsyncMock) as mock_tt:
        mock_tt.return_value = _MockDetails()
        result = await polygon_provider.get_fundamentals("AAPL")
        assert result["symbol"] == "AAPL"
        assert result["market_cap"] == 2_000_000_000_000


async def test_search_symbols(polygon_provider: PolygonProvider) -> None:
    with patch("quantagent.tools.providers.polygon.asyncio.to_thread", new_callable=AsyncMock) as mock_tt:
        mock_tt.return_value = [_MockTicker()]
        results = await polygon_provider.search_symbols("Apple")
        assert len(results) == 1
        assert results[0]["symbol"] == "AAPL"


async def test_get_news(polygon_provider: PolygonProvider) -> None:
    with patch("quantagent.tools.providers.polygon.asyncio.to_thread", new_callable=AsyncMock) as mock_tt:
        mock_tt.return_value = [_MockNewsItem()]
        results = await polygon_provider.get_news("AAPL", days=7)
        assert len(results) >= 1
        assert results[0]["title"] == "AAPL news"


async def test_get_news_empty(polygon_provider: PolygonProvider) -> None:
    with patch("quantagent.tools.providers.polygon.asyncio.to_thread", new_callable=AsyncMock) as mock_tt:
        mock_tt.return_value = []
        results = await polygon_provider.get_news("AAPL")
        assert results == []


async def test_get_earnings_calendar(polygon_provider: PolygonProvider) -> None:
    with patch("quantagent.tools.providers.polygon.asyncio.to_thread", new_callable=AsyncMock) as mock_tt:
        mock_tt.return_value = [_MockEarningsItem()]
        results = await polygon_provider.get_earnings_calendar("AAPL", lookahead_days=90)
        assert len(results) >= 1
        assert results[0]["eps_estimate"] == 2.0


async def test_get_earnings_calendar_empty(polygon_provider: PolygonProvider) -> None:
    with patch("quantagent.tools.providers.polygon.asyncio.to_thread", new_callable=AsyncMock) as mock_tt:
        mock_tt.return_value = []
        results = await polygon_provider.get_earnings_calendar("AAPL")
        assert results == []


async def test_get_sector_performance(polygon_provider: PolygonProvider) -> None:
    with patch("quantagent.tools.providers.polygon._fetch_sector_etf_history", new_callable=AsyncMock) as mock_fetch:
        dates = pd.date_range("2024-01-01", periods=100, freq="D", tz="UTC")
        df = pd.DataFrame({
            "Close": [100.0 + i * 0.1 for i in range(100)],
        }, index=dates)
        df["Open"] = df["Close"] * 0.99
        df["High"] = df["Close"] * 1.01
        df["Low"] = df["Close"] * 0.99
        df["Volume"] = 1_000_000
        mock_fetch.return_value = df
        results = await polygon_provider.get_sector_performance()
        assert "Technology" in results
        assert results["Technology"]["etf"] == "XLK"


async def test_get_sector_performance_empty(polygon_provider: PolygonProvider) -> None:
    with patch("quantagent.tools.providers.polygon._fetch_sector_etf_history", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = None
        results = await polygon_provider.get_sector_performance()
        assert results == {}


async def test_get_economic_indicators(polygon_provider: PolygonProvider) -> None:
    results = await polygon_provider.get_economic_indicators()
    assert results["vix"] is None
    assert results["gdp_growth"] is None


def test_init_empty_key_raises() -> None:
    with pytest.raises(ValueError, match="API key is required"):
        PolygonProvider(api_key="")


def test_period_to_start() -> None:
    from datetime import date
    end = date(2026, 7, 12)
    start = _period_to_start(end, "1y")
    assert (end - start).days == 365


def test_period_to_start_default() -> None:
    from datetime import date
    end = date(2026, 7, 12)
    start = _period_to_start(end, "unknown")
    assert (end - start).days == 365


def test_interval_to_timespan() -> None:
    assert _interval_to_timespan("1m") == "minute"
    assert _interval_to_timespan("1d") == "day"
    assert _interval_to_timespan("1wk") == "week"
    assert _interval_to_timespan("unknown") == "day"


def test_interval_multiplier() -> None:
    assert _interval_multiplier("15m") == 15
    assert _interval_multiplier("1d") == 1
    assert _interval_multiplier("unknown") == 1


def test_parse_news_timestamp_str() -> None:
    class _Item:
        published_utc = "2026-07-12T12:00:00Z"
    dt = _parse_news_timestamp(_Item())
    assert dt is not None
    assert dt.year == 2026


def test_parse_news_timestamp_none() -> None:
    class _Item:
        published_utc = None
    assert _parse_news_timestamp(_Item()) is None


def test_parse_news_timestamp_datetime() -> None:
    class _Item:
        published_utc = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
    dt = _parse_news_timestamp(_Item())
    assert dt is not None


def test_build_news_entry() -> None:
    entry = _build_news_entry(_MockNewsItem(), datetime(2026, 7, 12, 12, 0, tzinfo=UTC))
    assert entry["title"] == "AAPL news"
    assert entry["source"] == "Reuters"


def test_pct() -> None:
    s = pd.Series([100.0, 105.0, 110.0])
    assert abs(_pct(s, 1) - 0.0476) < 0.001


def test_pct_insufficient_data() -> None:
    s = pd.Series([100.0])
    assert _pct(s, 1) == 0.0


def test_ytd() -> None:
    dates = pd.date_range("2026-01-01", periods=200, freq="D", tz="UTC")
    s = pd.Series([100.0 + i * 0.1 for i in range(200)], index=dates)
    ytd_val = _ytd(s)
    assert ytd_val > 0


def test_ytd_insufficient_data() -> None:
    dates = pd.DatetimeIndex(["2024-01-01"], tz="UTC")
    s = pd.Series([100.0], index=dates)
    assert _ytd(s) == 0.0


async def test_get_quote_uses_ask_when_no_last(polygon_provider: PolygonProvider) -> None:
    class _NoLastQuote:
        def __init__(self) -> None:
            self.ask_price = 101.5
            self.bid_price = 100.5

    with patch("quantagent.tools.providers.polygon.asyncio.to_thread", new_callable=AsyncMock) as mock_tt:
        mock_tt.return_value = _NoLastQuote()
        result = await polygon_provider.get_quote("AAPL")
        assert result["price"] == 101.5


async def test_get_fundamentals_missing_attrs(polygon_provider: PolygonProvider) -> None:
    class _MinimalDetails:
        pass

    with patch("quantagent.tools.providers.polygon.asyncio.to_thread", new_callable=AsyncMock) as mock_tt:
        mock_tt.return_value = _MinimalDetails()
        result = await polygon_provider.get_fundamentals("AAPL")
        assert result["market_cap"] is None

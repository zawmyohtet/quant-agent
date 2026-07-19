"""Tests for Alpha Vantage provider."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from quantagent.tools.providers.alpha_vantage import (
    AlphaVantageProvider,
    _av_float,
    _av_int,
    _av_pct,
    _filter_by_period,
)


@pytest.fixture
def av_provider() -> AlphaVantageProvider:
    with patch("quantagent.tools.providers.alpha_vantage.TimeSeries"), \
         patch("quantagent.tools.providers.alpha_vantage.FundamentalData"), \
         patch("quantagent.tools.providers.alpha_vantage.AlphaIntelligence"), \
         patch("quantagent.tools.providers.alpha_vantage.EconIndicators"), \
         patch("quantagent.tools.providers.alpha_vantage.AlphaVantage"):
        return AlphaVantageProvider(api_key="test_key")


@patch("quantagent.tools.providers.alpha_vantage.asyncio.to_thread")
async def test_get_ohlcv(mock_to_thread: MagicMock, av_provider: AlphaVantageProvider) -> None:
    now = pd.Timestamp.now(tz="UTC")
    dates = pd.date_range(now - pd.Timedelta(days=4), periods=5, freq="D")
    df = pd.DataFrame({
        "1. open": [100.0] * 5,
        "2. high": [101.0] * 5,
        "3. low": [99.0] * 5,
        "4. close": [100.0] * 5,
        "6. volume": [1_000_000] * 5,
    }, index=dates)
    df.index = df.index.tz_localize(None)  # AV returns naive timestamps
    mock_to_thread.return_value = (df, None)
    result = await av_provider.get_ohlcv("AAPL", period="1y")
    assert "Close" in result.columns
    assert "Volume" in result.columns
    assert len(result) == 5


@patch("quantagent.tools.providers.alpha_vantage.asyncio.to_thread")
async def test_get_ohlcv_empty_raises(mock_to_thread: MagicMock, av_provider: AlphaVantageProvider) -> None:
    mock_to_thread.return_value = (pd.DataFrame(), None)
    with pytest.raises(ValueError, match="No OHLCV data"):
        await av_provider.get_ohlcv("AAPL")


@patch("quantagent.tools.providers.alpha_vantage.asyncio.to_thread")
async def test_get_quote(mock_to_thread: MagicMock, av_provider: AlphaVantageProvider) -> None:
    mock_to_thread.return_value = (
        {"05. price": "150.00", "09. change": "1.50", "10. change percent": "1.0%", "06. volume": "5000000"},
        None,
    )
    result = await av_provider.get_quote("AAPL")
    assert result["symbol"] == "AAPL"
    assert result["price"] == 150.0
    assert result["change_percent"] == 1.0


@patch("quantagent.tools.providers.alpha_vantage.asyncio.to_thread")
async def test_get_fundamentals(mock_to_thread: MagicMock, av_provider: AlphaVantageProvider) -> None:
    mock_to_thread.return_value = (
        {"PERatio": "15.0", "ReturnOnEquityTTM": "0.25"},
        None,
    )
    result = await av_provider.get_fundamentals("AAPL")
    assert result["pe_ratio"] == 15.0
    assert result["roe"] == 0.25


@patch("quantagent.tools.providers.alpha_vantage.asyncio.to_thread")
async def test_search_symbols(mock_to_thread: MagicMock, av_provider: AlphaVantageProvider) -> None:
    df = pd.DataFrame([{"1. symbol": "AAPL", "2. name": "Apple Inc", "4. region": "NASDAQ"}])
    mock_to_thread.return_value = (df, None)
    results = await av_provider.search_symbols("Apple")
    assert len(results) == 1
    assert results[0]["symbol"] == "AAPL"


@patch("quantagent.tools.providers.alpha_vantage.asyncio.to_thread")
async def test_search_symbols_empty(mock_to_thread: MagicMock, av_provider: AlphaVantageProvider) -> None:
    mock_to_thread.return_value = (pd.DataFrame(), None)
    results = await av_provider.search_symbols("Unknown")
    assert results == []


@patch("quantagent.tools.providers.alpha_vantage.asyncio.to_thread")
async def test_get_news(mock_to_thread: MagicMock, av_provider: AlphaVantageProvider) -> None:
    # Relative to now so it always falls inside get_news's day window.
    recent = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=1)).strftime("%Y%m%dT%H%M%S")
    mock_to_thread.return_value = (
        [
            {
                "title": "AAPL news",
                "source": "Reuters",
                "url": "https://example.com",
                "time_published": recent,
                "overall_sentiment_score": 0.5,
            }
        ],
        None,
    )
    results = await av_provider.get_news("AAPL", days=7)
    assert len(results) >= 1
    assert results[0]["sentiment"] == "positive"


@patch("quantagent.tools.providers.alpha_vantage.asyncio.to_thread")
async def test_get_news_non_list_data(mock_to_thread: MagicMock, av_provider: AlphaVantageProvider) -> None:
    mock_to_thread.return_value = ("not_a_list", None)
    results = await av_provider.get_news("AAPL")
    assert results == []


@patch("quantagent.tools.providers.alpha_vantage.asyncio.to_thread")
async def test_get_earnings_calendar(mock_to_thread: MagicMock, av_provider: AlphaVantageProvider) -> None:
    mock_to_thread.return_value = (
        {"earnings": [{"date": "2026-08-15", "estimatedEPS": "2.0", "reportedEPS": "2.1", "fiscalDateEnding": "2026Q3"}]},
        None,
    )
    results = await av_provider.get_earnings_calendar("AAPL", lookahead_days=90)
    assert len(results) >= 1
    assert results[0]["eps_estimate"] == 2.0


@patch("quantagent.tools.providers.alpha_vantage.asyncio.to_thread")
async def test_get_earnings_calendar_non_dict(mock_to_thread: MagicMock, av_provider: AlphaVantageProvider) -> None:
    mock_to_thread.return_value = ("not_a_dict", None)
    results = await av_provider.get_earnings_calendar("AAPL")
    assert results == []


@patch("quantagent.tools.providers.alpha_vantage.asyncio.to_thread")
async def test_get_sector_performance(mock_to_thread: MagicMock, av_provider: AlphaVantageProvider) -> None:
    mock_to_thread.return_value = (
        {
            "Energy": {"1D": "1.5%", "5D": "3.0%", "1M": "5.0%", "3M": "8.0%", "YTD": "12.0%"},
            "rank_a": {"Energy": 1},
        },
        None,
    )
    results = await av_provider.get_sector_performance()
    assert "Energy" in results
    assert results["Energy"]["performance_1d"] == 0.015


@patch("quantagent.tools.providers.alpha_vantage.asyncio.to_thread")
async def test_get_economic_indicators(mock_to_thread: MagicMock, av_provider: AlphaVantageProvider) -> None:
    mock_to_thread.side_effect = [
        (pd.DataFrame({"value": [4.5]}, index=pd.date_range("2026-01-01", periods=1)), None),
        (pd.DataFrame({"value": [3.0]}, index=pd.date_range("2026-01-01", periods=1)), None),
        (pd.DataFrame({"value": [2.0]}, index=pd.date_range("2026-01-01", periods=1)), None),
        (pd.DataFrame({"value": [3.2]}, index=pd.date_range("2026-01-01", periods=1)), None),
        (pd.DataFrame({"value": [4.1]}, index=pd.date_range("2026-01-01", periods=1)), None),
    ]
    results = await av_provider.get_economic_indicators()
    assert results["10y_yield"] == 4.5
    assert results["2y_yield"] == 3.0


@patch("quantagent.tools.providers.alpha_vantage.asyncio.to_thread")
async def test_get_economic_indicators_empty(mock_to_thread: MagicMock, av_provider: AlphaVantageProvider) -> None:
    mock_to_thread.side_effect = [
        (pd.DataFrame(), None),
        (pd.DataFrame(), None),
        (pd.DataFrame(), None),
        (pd.DataFrame(), None),
        (pd.DataFrame(), None),
    ]
    results = await av_provider.get_economic_indicators()
    assert results["10y_yield"] is None


def test_filter_by_period_keeps_recent() -> None:
    now = pd.Timestamp.now(tz="UTC")
    dates = pd.date_range(now - pd.Timedelta(days=400), periods=500, freq="D")
    df = pd.DataFrame({"Close": [100.0] * 500}, index=dates)
    result = _filter_by_period(df, "1y")
    assert len(result) < 500
    assert len(result) > 0


def test_filter_by_period_unknown_period() -> None:
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    df = pd.DataFrame({"Close": [100.0] * 10}, index=dates)
    result = _filter_by_period(df, "unknown")
    assert len(result) == 10


def test_av_float_none() -> None:
    assert _av_float({"key": "None"}, "key") is None


def test_av_float_missing() -> None:
    assert _av_float({}, "key") is None


def test_av_int() -> None:
    assert _av_int({"v": "42"}, "v") == 42


def test_av_int_none() -> None:
    assert _av_int({"v": "None"}, "v") is None


def test_av_pct() -> None:
    assert _av_pct({"v": "1.5%"}, "v") == 1.5


def test_av_pct_none() -> None:
    assert _av_pct({"v": "None"}, "v") is None


def test_av_pct_missing() -> None:
    assert _av_pct({}, "v") is None


def test_init_empty_key_raises() -> None:
    with pytest.raises(ValueError, match="API key is required"):
        AlphaVantageProvider(api_key="")

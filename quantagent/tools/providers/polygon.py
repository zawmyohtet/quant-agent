"""Polygon.io data provider implementation."""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
from polygon import RESTClient  # type: ignore[import-untyped]

from quantagent.tools.providers.base import AbstractDataProvider

logger = logging.getLogger(__name__)


class PolygonProvider(AbstractDataProvider):
    """Market data via Polygon.io API."""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("Polygon API key is required")
        self.api_key = api_key
        self._client = RESTClient(api_key)

    async def get_ohlcv(
        self, symbol: str, period: str = "1y", interval: str = "1d"
    ) -> pd.DataFrame:
        """Fetch OHLCV data."""
        end = datetime.now(UTC).date()
        start = _period_to_start(end, period)
        timespan = _interval_to_timespan(interval)
        multiplier = _interval_multiplier(interval)

        aggs = await asyncio.to_thread(
            self._client.get_aggs,
            symbol,
            multiplier,
            timespan,
            start,
            end,
            limit=50000,
        )
        if not aggs:
            raise ValueError(f"No OHLCV data returned for {symbol}")

        records = []
        for agg in aggs:
            records.append(
                {
                    "Date": datetime.fromtimestamp(agg.timestamp / 1000, tz=UTC),
                    "Open": agg.open,
                    "High": agg.high,
                    "Low": agg.low,
                    "Close": agg.close,
                    "Volume": agg.volume,
                }
            )
        df = pd.DataFrame(records).set_index("Date").sort_index()
        return df

    async def get_quote(self, symbol: str) -> dict:
        """Fetch current quote."""
        quote = await asyncio.to_thread(self._client.get_last_quote, symbol)
        return {
            "symbol": symbol,
            "price": quote.last_price if hasattr(quote, "last_price") else quote.ask_price,
            "change": None,
            "change_percent": None,
            "volume": None,
            "market_cap": None,
            "bid": quote.bid_price if hasattr(quote, "bid_price") else None,
            "ask": quote.ask_price if hasattr(quote, "ask_price") else None,
        }

    async def get_fundamentals(self, symbol: str) -> dict:
        """Fetch fundamental data."""
        details = await asyncio.to_thread(self._client.get_ticker_details, symbol)
        return {
            "symbol": symbol,
            "pe_ratio": None,
            "pb_ratio": None,
            "ev_ebitda": None,
            "roe": None,
            "roa": None,
            "debt_equity": None,
            "free_cash_flow": None,
            "dividend_yield": None,
            "eps": None,
            "revenue_growth": None,
            "eps_growth": None,
            "beta": None,
            "market_cap": details.market_cap if hasattr(details, "market_cap") else None,
            "shares_outstanding": details.share_class_shares_outstanding
            if hasattr(details, "share_class_shares_outstanding")
            else None,
            "employees": details.total_employees if hasattr(details, "total_employees") else None,
            "sector": details.sic_description if hasattr(details, "sic_description") else None,
        }

    async def search_symbols(self, query: str) -> list[dict]:
        """Search for symbols."""
        tickers = await asyncio.to_thread(self._client.list_tickers, search=query, limit=20)
        results = []
        for t in tickers:
            results.append(
                {
                    "symbol": t.ticker,
                    "name": t.name,
                    "exchange": t.primary_exchange,
                }
            )
        return results

    async def get_news(self, symbol: str, days: int = 7) -> list[dict]:
        """Fetch news headlines."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        news_items = await asyncio.to_thread(
            self._client.list_ticker_news, ticker=symbol, limit=50
        )
        results = []
        for item in news_items:
            pub_dt = _parse_news_timestamp(item)
            if pub_dt is not None and pub_dt >= cutoff:
                results.append(_build_news_entry(item, pub_dt))
        return results


def _period_to_start(end_date: Any, period: str) -> Any:
    """Convert a period string to a start date."""
    delta_map = {
        "1d": timedelta(days=1),
        "5d": timedelta(days=5),
        "1mo": timedelta(days=30),
        "3mo": timedelta(days=90),
        "6mo": timedelta(days=180),
        "1y": timedelta(days=365),
        "2y": timedelta(days=730),
        "5y": timedelta(days=1825),
        "10y": timedelta(days=3650),
    }
    delta = delta_map.get(period, timedelta(days=365))
    return end_date - delta


def _interval_to_timespan(interval: str) -> str:
    """Convert interval string to Polygon timespan."""
    mapping = {
        "1m": "minute",
        "2m": "minute",
        "5m": "minute",
        "15m": "minute",
        "30m": "minute",
        "60m": "hour",
        "1h": "hour",
        "1d": "day",
        "5d": "day",
        "1wk": "week",
        "1mo": "month",
    }
    return mapping.get(interval, "day")


def _interval_multiplier(interval: str) -> int:
    """Extract multiplier from interval string."""
    mapping = {
        "1m": 1,
        "2m": 2,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "60m": 60,
        "1h": 1,
        "1d": 1,
        "5d": 5,
        "1wk": 1,
        "1mo": 1,
    }
    return mapping.get(interval, 1)


def _parse_news_timestamp(item: Any) -> datetime | None:
    """Extract and parse the published_utc timestamp from a news item."""
    pub_dt = getattr(item, "published_utc", None)
    if pub_dt is None:
        return None
    if isinstance(pub_dt, str):
        return datetime.fromisoformat(pub_dt.replace("Z", "+00:00"))
    return pub_dt  # type: ignore[no-any-return]


def _build_news_entry(item: Any, pub_dt: datetime | None) -> dict:
    """Build a news entry dict from a Polygon news item."""
    publisher = getattr(item, "publisher", None)
    return {
        "title": getattr(item, "title", ""),
        "source": publisher.name if publisher is not None else "",
        "url": getattr(item, "article_url", ""),
        "published_at": pub_dt.isoformat() if pub_dt is not None else "",
        "sentiment": "neutral",
    }

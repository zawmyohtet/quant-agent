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

_POLYGON_SECTOR_ETFS: dict[str, str] = {
    "Technology": "XLK",
    "Healthcare": "XLV",
    "Financials": "XLF",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Communication Services": "XLC",
}


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

    async def get_earnings_calendar(
        self, symbol: str, lookahead_days: int = 90
    ) -> list[dict]:
        """Fetch upcoming earnings via Polygon earnings calendar API."""
        cutoff = datetime.now(UTC) + timedelta(days=lookahead_days)
        earnings = await asyncio.to_thread(
            self._client.get_earnings_calendar, symbol=symbol.upper()
        )
        if not earnings:
            return []
        results = []
        for item in earnings:
            date_str = getattr(item, "report_date", None) or getattr(item, "calendar_date", None)
            if not date_str:
                continue
            try:
                dt = datetime.fromisoformat(str(date_str)).replace(tzinfo=UTC)
            except ValueError:
                continue
            if dt > cutoff:
                continue
            results.append(
                {
                    "symbol": symbol.upper(),
                    "date": dt.isoformat(),
                    "eps_estimate": getattr(item, "estimated_eps", None),
                    "eps_actual": getattr(item, "reported_eps", None),
                    "quarter": getattr(item, "fiscal_period", ""),
                }
            )
        return results

    async def get_sector_performance(self) -> dict:
        """Compute sector performance from Sector SPDR ETFs via Polygon."""
        results: dict[str, dict] = {}
        for sector_name, etf_symbol in _POLYGON_SECTOR_ETFS.items():
            hist = await _fetch_sector_etf_history(self._client, etf_symbol)
            if hist is None or hist.empty:
                continue
            close = hist["Close"]
            if len(close) < 5:
                continue
            results[sector_name] = {
                "etf": etf_symbol,
                "price": round(float(close.iloc[-1]), 4),
                "performance_1d": round(_pct(close, 1), 4),
                "performance_1w": round(_pct(close, 5), 4),
                "performance_1m": round(_pct(close, 21), 4),
                "performance_3m": round(_pct(close, 63), 4),
                "performance_ytd": round(_ytd(close), 4),
                "best_stock": None,
            }
        return results

    async def get_economic_indicators(self) -> dict:
        """Polygon does not support economic indicators."""
        logger.warning("economic_indicators not available via Polygon")
        return {
            "vix": None,
            "10y_yield": None,
            "2y_yield": None,
            "sp500_pe": None,
            "gdp_growth": None,
            "cpi": None,
            "unemployment_rate": None,
        }


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


async def _fetch_sector_etf_history(
    client: RESTClient, symbol: str
) -> pd.DataFrame | None:
    """Fetch 1 year of daily OHLCV for a sector ETF."""
    end = datetime.now(UTC).date()
    start = end - timedelta(days=365)
    try:
        aggs = await asyncio.to_thread(
            client.get_aggs, symbol, 1, "day", start, end, limit=500
        )
    except Exception:
        logger.warning("Failed to fetch ETF history for %s", symbol)
        return None
    if not aggs:
        return None
    records = [
        {
            "Date": datetime.fromtimestamp(a.timestamp / 1000, tz=UTC),
            "Open": a.open,
            "High": a.high,
            "Low": a.low,
            "Close": a.close,
            "Volume": a.volume,
        }
        for a in aggs
    ]
    return pd.DataFrame(records).set_index("Date").sort_index()


def _pct(series: pd.Series, periods: int) -> float:
    """Percentage change over N periods."""
    if len(series) <= periods:
        return 0.0
    return float(series.iloc[-1] / series.iloc[-(periods + 1)] - 1)


def _ytd(series: pd.Series) -> float:
    """Year-to-date return."""
    now = datetime.now(UTC)
    ytd_start = datetime(now.year, 1, 1, tzinfo=UTC)
    ytd_data = series[series.index >= ytd_start]
    if len(ytd_data) < 2:
        return 0.0
    return float(ytd_data.iloc[-1] / ytd_data.iloc[0] - 1)

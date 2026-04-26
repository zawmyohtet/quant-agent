"""YFinance data provider implementation."""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import pandas as pd
import yfinance as yf  # type: ignore[import-untyped]

from quantagent.tools.providers.base import AbstractDataProvider

logger = logging.getLogger(__name__)


class YFinanceProvider(AbstractDataProvider):
    """Free market data via yfinance (Yahoo Finance)."""

    async def get_ohlcv(
        self, symbol: str, period: str = "1y", interval: str = "1d"
    ) -> pd.DataFrame:
        """Fetch OHLCV data."""
        ticker = yf.Ticker(symbol)
        df: pd.DataFrame = await asyncio.to_thread(ticker.history, period=period, interval=interval)
        if df.empty:
            raise ValueError(f"No OHLCV data returned for {symbol}")
        # Keep only OHLCV columns, convert to UTC
        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.index = pd.DatetimeIndex(df.index).tz_convert(UTC)
        df.index.name = "Date"
        return df

    async def get_quote(self, symbol: str) -> dict:
        """Fetch current quote."""
        ticker = yf.Ticker(symbol)
        info = await asyncio.to_thread(lambda: ticker.info)
        return {
            "symbol": symbol,
            "price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "change": info.get("regularMarketChange"),
            "change_percent": info.get("regularMarketChangePercent"),
            "volume": info.get("regularMarketVolume") or info.get("volume"),
            "market_cap": info.get("marketCap"),
            "bid": info.get("bid"),
            "ask": info.get("ask"),
            "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
        }

    async def get_fundamentals(self, symbol: str) -> dict:
        """Fetch fundamental data."""
        ticker = yf.Ticker(symbol)
        info = await asyncio.to_thread(lambda: ticker.info)
        return {
            "symbol": symbol,
            "pe_ratio": info.get("trailingPE"),
            "pb_ratio": info.get("priceToBook"),
            "ev_ebitda": info.get("enterpriseToEbitda"),
            "roe": info.get("returnOnEquity"),
            "roa": info.get("returnOnAssets"),
            "debt_equity": info.get("debtToEquity"),
            "free_cash_flow": info.get("freeCashflow"),
            "dividend_yield": info.get("dividendYield"),
            "eps": info.get("trailingEps"),
            "revenue_growth": info.get("revenueGrowth"),
            "eps_growth": info.get("earningsGrowth"),
            "beta": info.get("beta"),
        }

    async def search_symbols(self, query: str) -> list[dict]:
        """Search for symbols by company name."""
        search = await asyncio.to_thread(yf.Search, query, max_results=20)
        quotes = search.quotes or []
        return [
            {
                "symbol": q.get("symbol"),
                "name": q.get("longname") or q.get("shortname"),
                "exchange": q.get("exchDisp") or q.get("exchange"),
            }
            for q in quotes
            if q.get("symbol")
        ]

    async def get_news(self, symbol: str, days: int = 7) -> list[dict]:
        """Fetch news headlines."""
        ticker = yf.Ticker(symbol)
        news = await asyncio.to_thread(lambda: ticker.news)
        cutoff = datetime.now(UTC) - timedelta(days=days)
        results = []
        for item in news or []:
            content = item.get("content", item)
            pub_time = content.get("pubDate") or content.get("providerPublishTime")
            if isinstance(pub_time, (int, float)):
                pub_dt = datetime.fromtimestamp(pub_time, tz=UTC)
            elif isinstance(pub_time, str):
                pub_dt = datetime.fromisoformat(pub_time.replace("Z", "+00:00"))
            else:
                continue
            if pub_dt < cutoff:
                continue
            results.append(
                {
                    "title": content.get("title", ""),
                    "source": content.get("provider", {}).get("displayName", "")
                    if isinstance(content.get("provider"), dict)
                    else content.get("publisher", ""),
                    "url": content.get("canonicalUrl", {}).get("url", "")
                    if isinstance(content.get("canonicalUrl"), dict)
                    else content.get("link", ""),
                    "published_at": pub_dt.isoformat(),
                    "sentiment": "neutral",
                }
            )
        return results

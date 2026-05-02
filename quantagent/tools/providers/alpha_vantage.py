"""Alpha Vantage data provider implementation."""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import pandas as pd
from alpha_vantage.alphaintelligence import AlphaIntelligence  # type: ignore[import-untyped]
from alpha_vantage.fundamentaldata import FundamentalData  # type: ignore[import-untyped]
from alpha_vantage.sectorperformance import SectorPerformances  # type: ignore[import-untyped]
from alpha_vantage.timeseries import TimeSeries  # type: ignore[import-untyped]

from quantagent.tools.providers.base import AbstractDataProvider

logger = logging.getLogger(__name__)


class AlphaVantageProvider(AbstractDataProvider):
    """Market data via Alpha Vantage API."""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("Alpha Vantage API key is required")
        self.api_key = api_key
        self._ts = TimeSeries(key=api_key, output_format="pandas")
        self._fd = FundamentalData(key=api_key, output_format="pandas")
        self._ai = AlphaIntelligence(key=api_key)
        self._sp = SectorPerformances(key=api_key, output_format="pandas")

    async def get_ohlcv(
        self, symbol: str, period: str = "1y", interval: str = "1d"
    ) -> pd.DataFrame:
        """Fetch OHLCV data."""
        df: pd.DataFrame = (await asyncio.to_thread(self._ts.get_daily_adjusted, symbol, outputsize="full"))[0]
        if df.empty:
            raise ValueError(f"No OHLCV data returned for {symbol}")
        # Rename columns to standard names
        rename_map = {
            "1. open": "Open",
            "2. high": "High",
            "3. low": "Low",
            "4. close": "Close",
            "5. adjusted close": "Close",
            "6. volume": "Volume",
        }
        df = df.rename(columns=rename_map)
        # Keep only standard columns that exist
        keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
        df = df[keep].copy()
        df.index = pd.to_datetime(df.index)
        df.index = df.index.tz_localize(UTC)
        # Filter by period
        df = _filter_by_period(df, period)
        return df.sort_index()

    async def get_quote(self, symbol: str) -> dict:
        """Fetch current quote."""
        data, _ = await asyncio.to_thread(self._ts.get_quote_endpoint, symbol)
        if isinstance(data, pd.DataFrame):
            data = data.to_dict("records")[0]
        return {
            "symbol": symbol,
            "price": _av_float(data, "05. price"),
            "change": _av_float(data, "09. change"),
            "change_percent": _av_pct(data, "10. change percent"),
            "volume": _av_int(data, "06. volume"),
            "market_cap": None,
            "bid": None,
            "ask": None,
        }

    async def get_fundamentals(self, symbol: str) -> dict:
        """Fetch fundamental data."""
        data, _ = await asyncio.to_thread(self._fd.get_company_overview, symbol)
        if isinstance(data, pd.DataFrame):
            data = data.to_dict("records")[0] if len(data) > 0 else {}
        return {
            "symbol": symbol,
            "pe_ratio": _av_float(data, "PERatio"),
            "pb_ratio": _av_float(data, "PriceToBookRatio"),
            "ev_ebitda": _av_float(data, "EVToEBITDA"),
            "roe": _av_float(data, "ReturnOnEquityTTM"),
            "roa": _av_float(data, "ReturnOnAssetsTTM"),
            "debt_equity": _av_float(data, "DebtToEquityRatio"),
            "free_cash_flow": _av_float(data, "FreeCashFlowPerShareTTM"),
            "dividend_yield": _av_float(data, "DividendYield"),
            "eps": _av_float(data, "EPS"),
            "revenue_growth": _av_float(data, "QuarterlyRevenueGrowthYOY"),
            "eps_growth": _av_float(data, "QuarterlyEarningsGrowthYOY"),
            "beta": _av_float(data, "Beta"),
        }

    async def search_symbols(self, query: str) -> list[dict]:
        """Search for symbols."""
        df, _ = await asyncio.to_thread(self._ts.get_symbol_search, query)
        if df.empty:
            return []
        records = df.to_dict("records")
        return [
            {
                "symbol": r.get("1. symbol", ""),
                "name": r.get("2. name", ""),
                "exchange": r.get("4. region", ""),
            }
            for r in records
        ]

    async def get_news(self, symbol: str, days: int = 7) -> list[dict]:
        """Fetch news headlines."""
        data, _ = await asyncio.to_thread(self._ai.get_news_sentiment, tickers=symbol, limit=50)
        if not isinstance(data, list):
            return []
        cutoff = datetime.now(UTC) - timedelta(days=days)
        results = []
        for item in data:
            pub_str = item.get("time_published", "")
            if not pub_str:
                continue
            try:
                pub_dt = datetime.strptime(pub_str, "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
            except ValueError:
                continue
            if pub_dt < cutoff:
                continue
            sentiment = item.get("overall_sentiment_score", 0)
            sentiment_label = (
                "positive" if sentiment > 0.25 else "negative" if sentiment < -0.25 else "neutral"
            )
            results.append(
                {
                    "title": item.get("title", ""),
                    "source": item.get("source", ""),
                    "url": item.get("url", ""),
                    "published_at": pub_dt.isoformat(),
                    "sentiment": sentiment_label,
                }
            )
        return results


    async def get_earnings_calendar(
        self, symbol: str, lookahead_days: int = 90
    ) -> list[dict]:
        """Fetch upcoming earnings dates via Alpha Vantage."""
        data, _ = await asyncio.to_thread(
            self._ai.get_earnings, symbol=symbol.upper()
        )
        if not isinstance(data, dict) or "earnings" not in data:
            return []
        cutoff = datetime.now(UTC) + timedelta(days=lookahead_days)
        results = []
        for item in data["earnings"]:
            date_str = item.get("date")
            if not date_str:
                continue
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
            except ValueError:
                continue
            if dt > cutoff:
                continue
            results.append(
                {
                    "symbol": symbol.upper(),
                    "date": dt.isoformat(),
                    "eps_estimate": _av_float(item, "estimatedEPS"),
                    "eps_actual": _av_float(item, "reportedEPS"),
                    "quarter": item.get("fiscalDateEnding", ""),
                }
            )
        return results

    async def get_sector_performance(self) -> dict:
        """Fetch sector performance via Alpha Vantage SectorPerformances API."""
        data, _ = await asyncio.to_thread(self._sp.get_sector)
        if not isinstance(data, dict):
            return {}
        rank_meta = data.get("rank_a", {})
        results: dict[str, dict] = {}
        for key in [
            "Energy", "Materials", "Industrials", "Consumer Discretionary",
            "Consumer Staples", "Healthcare", "Financials", "Technology",
            "Communication Services", "Utilities", "Real Estate",
        ]:
            perf_data = data.get(key)
            if not isinstance(perf_data, dict):
                continue
            results[key] = {
                "performance_1d": _av_pct_val(perf_data.get("1D")),
                "performance_1w": _av_pct_val(perf_data.get("5D")),
                "performance_1m": _av_pct_val(perf_data.get("1M")),
                "performance_3m": _av_pct_val(perf_data.get("3M")),
                "performance_ytd": _av_pct_val(perf_data.get("YTD")),
                "rank": _av_int(rank_meta, key),
                "best_stock": None,
            }
        return results

    async def get_economic_indicators(self) -> dict:
        """Fetch economic indicators via Alpha Vantage."""
        indicators: dict[str, float | None] = {
            "vix": None,
            "10y_yield": None,
            "2y_yield": None,
            "sp500_pe": None,
            "gdp_growth": None,
            "cpi": None,
            "unemployment_rate": None,
        }
        ten_y = await _fetch_treasury_yield(self._ts, "10year")
        two_y = await _fetch_treasury_yield(self._ts, "2year")
        indicators["10y_yield"] = ten_y
        indicators["2y_yield"] = two_y
        indicators["gdp_growth"] = await _fetch_economic_indicator(self._ts, "real_gdp")
        indicators["cpi"] = await _fetch_economic_indicator(self._ts, "cpi")
        indicators["unemployment_rate"] = await _fetch_economic_indicator(
            self._ts, "unemployment"
        )
        logger.warning("vix and sp500_pe not available via Alpha Vantage")
        return indicators


def _av_pct_val(val: str | None) -> float | None:
    """Convert Alpha Vantage percentage string (e.g. '1.23%') to float."""
    if val is None:
        return None
    try:
        return round(float(val.replace("%", "")) / 100, 4)
    except (ValueError, TypeError, AttributeError):
        return None


async def _fetch_treasury_yield(ts: TimeSeries, maturity: str) -> float | None:
    """Fetch latest treasury yield for a given maturity."""
    data, _ = await asyncio.to_thread(
        ts.get_treasury_yield, interval="monthly", maturity=maturity
    )
    if not isinstance(data, pd.DataFrame) or data.empty:
        return None
    return round(float(data.iloc[-1]["value"]), 4)


async def _fetch_economic_indicator(ts: TimeSeries, name: str) -> float | None:
    """Fetch latest value for an economic indicator."""
    try:
        data, _ = await asyncio.to_thread(ts.get_economic_indicator, name=name)
        if not isinstance(data, pd.DataFrame) or data.empty:
            return None
        return round(float(data.iloc[-1][name]), 4)
    except Exception:
        logger.warning("Failed to fetch economic indicator: %s", name)
        return None


def _filter_by_period(df: pd.DataFrame, period: str) -> pd.DataFrame:
    """Filter DataFrame to the requested period."""
    now = datetime.now(UTC)
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
    delta = delta_map.get(period)
    if delta:
        return df[df.index >= now - delta]
    return df


def _av_float(data: dict, key: str) -> float | None:
    """Safely extract a float from Alpha Vantage response."""
    try:
        val = data.get(key)
        if val is None or val == "None":
            return None
        return float(val)
    except (ValueError, TypeError):
        return None


def _av_int(data: dict, key: str) -> int | None:
    """Safely extract an int from Alpha Vantage response."""
    try:
        val = data.get(key)
        if val is None or val == "None":
            return None
        return int(val)
    except (ValueError, TypeError):
        return None


def _av_pct(data: dict, key: str) -> float | None:
    """Safely extract a percentage from Alpha Vantage response."""
    try:
        val = data.get(key)
        if val is None or val == "None":
            return None
        return float(val.replace("%", ""))
    except (ValueError, TypeError, AttributeError):
        return None

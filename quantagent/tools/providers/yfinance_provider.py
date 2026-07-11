"""YFinance data provider implementation."""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import cast

import pandas as pd
import yfinance as yf  # type: ignore[import-untyped]

from quantagent.tools.providers.base import AbstractDataProvider

logger = logging.getLogger(__name__)

_SECTOR_ETFS: dict[str, str] = {
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

_ECON_TICKERS: dict[str, str] = {
    "vix": "^VIX",
    "10y_yield": "^TNX",
    "2y_yield": "^IRX",
    "sp500": "^GSPC",
}


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

    async def get_batch_ohlcv(
        self, symbols: list[str], period: str = "1y", interval: str = "1d"
    ) -> dict[str, pd.DataFrame]:
        """Fetch OHLCV for multiple symbols in one yf.download request."""
        if not symbols:
            return {}
        raw: pd.DataFrame = await asyncio.to_thread(
            yf.download,
            tickers=list(symbols),
            period=period,
            interval=interval,
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
        return _split_batch_frame(raw, symbols)

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

    async def get_earnings_calendar(
        self, symbol: str, lookahead_days: int = 90
    ) -> list[dict]:
        """Fetch upcoming earnings dates via yfinance calendar."""
        ticker = yf.Ticker(symbol.upper())
        cal = await asyncio.to_thread(lambda: ticker.calendar)
        if not cal or "Earnings Date" not in cal:
            return []
        earnings_dates = cal.get("Earnings Date", [])
        if not isinstance(earnings_dates, list):
            earnings_dates = [earnings_dates]
        cutoff = datetime.now(UTC) + timedelta(days=lookahead_days)
        results = []
        for date_val in earnings_dates:
            if isinstance(date_val, (int, float)):
                dt = datetime.fromtimestamp(date_val, tz=UTC)
            elif isinstance(date_val, datetime):
                dt = date_val if date_val.tzinfo else date_val.replace(tzinfo=UTC)
            else:
                continue
            if dt > cutoff:
                continue
            results.append(
                {
                    "symbol": symbol.upper(),
                    "date": dt.isoformat(),
                    "eps_estimate": None,
                    "eps_actual": None,
                    "quarter": f"Q{dt.month // 3 + 1}-{dt.year}",
                }
            )
        return results

    async def get_sector_performance(self) -> dict:
        """Compute sector performance from Sector SPDR ETFs."""
        results: dict[str, dict] = {}
        for sector_name, etf_symbol in _SECTOR_ETFS.items():
            ticker = yf.Ticker(etf_symbol)
            hist: pd.DataFrame = await asyncio.to_thread(
                ticker.history, period="1y", interval="1d"
            )
            if hist.empty:
                logger.warning("No data for sector ETF %s (%s)", etf_symbol, sector_name)
                continue
            close = hist["Close"]
            if len(close) < 5:
                continue
            latest = close.iloc[-1]
            perf_1d = _pct_change(close, 1)
            perf_1w = _pct_change(close, 5)
            perf_1m = _pct_change(close, 21)
            perf_3m = _pct_change(close, 63)
            perf_ytd = _ytd_return(close)
            results[sector_name] = {
                "etf": etf_symbol,
                "price": round(float(latest), 4),
                "performance_1d": round(perf_1d, 4) if perf_1d is not None else None,
                "performance_1w": round(perf_1w, 4) if perf_1w is not None else None,
                "performance_1m": round(perf_1m, 4) if perf_1m is not None else None,
                "performance_3m": round(perf_3m, 4) if perf_3m is not None else None,
                "performance_ytd": round(perf_ytd, 4) if perf_ytd is not None else None,
                "best_stock": None,
            }
        return results

    async def get_economic_indicators(self) -> dict:
        """Fetch economic indicators via yfinance tickers."""
        indicators: dict[str, float | None] = {
            "vix": None,
            "10y_yield": None,
            "2y_yield": None,
            "sp500_pe": None,
            "gdp_growth": None,
            "cpi": None,
            "unemployment_rate": None,
        }
        vix_symbol = _ECON_TICKERS["vix"]
        tn10_symbol = _ECON_TICKERS["10y_yield"]
        irx_symbol = _ECON_TICKERS["2y_yield"]
        sp500_symbol = _ECON_TICKERS["sp500"]

        async def _fetch_latest(symbol: str) -> float | None:
            ticker = yf.Ticker(symbol)
            hist: pd.DataFrame = await asyncio.to_thread(
                ticker.history, period="5d", interval="1d"
            )
            if hist.empty:
                return None
            return round(float(hist["Close"].iloc[-1]), 4)

        vix = await _fetch_latest(vix_symbol)
        tn10 = await _fetch_latest(tn10_symbol)
        irx = await _fetch_latest(irx_symbol)
        sp500 = await _fetch_latest(sp500_symbol)

        indicators["vix"] = vix
        indicators["10y_yield"] = round(tn10 / 10, 4) if tn10 else None
        indicators["2y_yield"] = round(irx / 10, 4) if irx else None
        indicators["sp500_pe"] = sp500

        logger.warning(
            "gdp_growth, cpi, unemployment_rate not available via yfinance"
        )
        return indicators


def _split_batch_frame(raw: pd.DataFrame, symbols: list[str]) -> dict[str, pd.DataFrame]:
    """Split a multi-ticker yf.download frame into per-symbol OHLCV frames."""
    if raw is None or raw.empty:
        return {}
    results: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        frame = _extract_symbol_frame(raw, sym, len(symbols))
        if frame is not None:
            results[sym] = frame
    return results


def _extract_symbol_frame(
    raw: pd.DataFrame, symbol: str, n_symbols: int
) -> pd.DataFrame | None:
    """Extract and normalize one symbol's OHLCV frame from a batch download."""
    if isinstance(raw.columns, pd.MultiIndex):
        if symbol not in raw.columns.get_level_values(0):
            logger.warning("Batch download returned no data for %s", symbol)
            return None
        frame = cast(pd.DataFrame, raw[symbol])
    elif n_symbols == 1:
        frame = raw
    else:
        return None
    return _normalize_ohlcv_frame(frame)


def _normalize_ohlcv_frame(frame: pd.DataFrame) -> pd.DataFrame | None:
    """Restrict to OHLCV columns, drop empty rows, convert index to UTC."""
    cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in frame.columns]
    if not cols:
        return None
    result = frame[cols].dropna(how="all").copy()
    if result.empty:
        return None
    index = pd.DatetimeIndex(result.index)
    result.index = index.tz_localize(UTC) if index.tz is None else index.tz_convert(UTC)
    result.index.name = "Date"
    return result


def _pct_change(series: pd.Series, periods: int) -> float | None:
    """Compute percentage change over N periods."""
    if len(series) <= periods:
        return None
    return float(series.iloc[-1] / series.iloc[-(periods + 1)] - 1)


def _ytd_return(series: pd.Series) -> float | None:
    """Compute year-to-date return."""
    now = datetime.now(UTC)
    ytd_start = datetime(now.year, 1, 1, tzinfo=UTC)
    ytd_mask = series.index >= ytd_start
    ytd_data = series[ytd_mask]
    if len(ytd_data) < 2:
        return None
    return float(ytd_data.iloc[-1] / ytd_data.iloc[0] - 1)

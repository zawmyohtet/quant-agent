"""Stock screener tool functions."""
from __future__ import annotations

import logging
from io import StringIO

import pandas as pd
import requests

from quantagent.tools.providers.base import AbstractDataProvider

logger = logging.getLogger(__name__)

_UNIVERSE_URLS = {
    "sp500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "nasdaq100": "https://en.wikipedia.org/wiki/Nasdaq-100",
}

_WIKI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


def _fetch_universe_tickers(universe: str) -> list[str]:
    """Fetch ticker list for a universe from Wikipedia."""
    url = _UNIVERSE_URLS.get(universe)
    if not url:
        logger.warning("Unknown universe: %s", universe)
        return []

    try:
        resp = requests.get(url, headers=_WIKI_HEADERS, timeout=30)
        resp.raise_for_status()
        tables = pd.read_html(StringIO(resp.text))
        if universe == "sp500":
            return list(tables[0]["Symbol"].tolist())
        if universe == "nasdaq100":
            # Nasdaq-100 table usually has 'Ticker' or 'Symbol' column
            for table in tables:
                for col in ["Ticker", "Symbol", " ticker"]:
                    if col in table.columns:
                        return list(table[col].dropna().astype(str).tolist())
            return []
    except Exception as exc:
        logger.warning("Failed to fetch %s universe: %s", universe, exc)
        return []
    return []


async def screen_stocks(
    provider: AbstractDataProvider,
    universe: str = "sp500",
    criteria: dict | None = None,
    sort_by: str = "market_cap",
    ascending: bool = False,
    limit: int = 20,
) -> pd.DataFrame:
    """Screen stocks by fundamental and technical criteria.

    Supported criteria keys: pe_lt/gt, pb_lt, roe_gt, roa_gt, debt_equity_lt,
    mcap_gt/lt, volume_gt, dividend_yield_gt, revenue_growth_gt, eps_growth_gt,
    rsi_lt/gt, beta_lt.
    """
    criteria = criteria or {}
    tickers = _fetch_universe_tickers(universe)
    if not tickers:
        logger.warning("No tickers found for universe: %s", universe)
        return pd.DataFrame()

    # Limit screening scope for performance
    max_screen = min(len(tickers), 100)
    tickers = tickers[:max_screen]

    rows = []
    for ticker in tickers:
        try:
            fundamentals = await provider.get_fundamentals(ticker)
            quote = await provider.get_quote(ticker)
            row = {
                "symbol": ticker,
                "name": fundamentals.get("name", ""),
                "pe_ratio": fundamentals.get("pe_ratio"),
                "pb_ratio": fundamentals.get("pb_ratio"),
                "roe": fundamentals.get("roe"),
                "roa": fundamentals.get("roa"),
                "debt_equity": fundamentals.get("debt_equity"),
                "market_cap": quote.get("market_cap"),
                "volume": quote.get("volume"),
                "dividend_yield": fundamentals.get("dividend_yield"),
                "revenue_growth": fundamentals.get("revenue_growth"),
                "eps_growth": fundamentals.get("eps_growth"),
                "beta": fundamentals.get("beta"),
                "price": quote.get("price"),
            }
            rows.append(row)
        except Exception as exc:
            logger.debug("Skipping %s: %s", ticker, exc)
            continue

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Apply criteria filters
    for key, value in criteria.items():
        try:
            if key == "pe_lt":
                df = df[df["pe_ratio"] < value]
            elif key == "pe_gt":
                df = df[df["pe_ratio"] > value]
            elif key == "pb_lt":
                df = df[df["pb_ratio"] < value]
            elif key == "roe_gt":
                df = df[df["roe"] > value]
            elif key == "roa_gt":
                df = df[df["roa"] > value]
            elif key == "debt_equity_lt":
                df = df[df["debt_equity"] < value]
            elif key == "mcap_gt":
                df = df[df["market_cap"] > value]
            elif key == "mcap_lt":
                df = df[df["market_cap"] < value]
            elif key == "volume_gt":
                df = df[df["volume"] > value]
            elif key == "dividend_yield_gt":
                df = df[df["dividend_yield"] > value]
            elif key == "revenue_growth_gt":
                df = df[df["revenue_growth"] > value]
            elif key == "eps_growth_gt":
                df = df[df["eps_growth"] > value]
            elif key == "rsi_lt":
                df = df[df["rsi"] < value]
            elif key == "rsi_gt":
                df = df[df["rsi"] > value]
            elif key == "beta_lt":
                df = df[df["beta"] < value]
            else:
                logger.warning("Unknown criteria key: %s", key)
        except Exception as exc:
            logger.warning("Failed to apply criteria %s: %s", key, exc)

    if sort_by in df.columns:
        df = df.sort_values(by=sort_by, ascending=ascending, na_position="last")

    return df.head(limit).reset_index(drop=True)

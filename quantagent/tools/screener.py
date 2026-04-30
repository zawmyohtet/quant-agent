"""Stock screener tool functions."""
from __future__ import annotations

import logging
import operator as op_module
from collections.abc import Callable
from io import StringIO
from typing import Any

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
    df = _apply_criteria(df, criteria)

    if sort_by in df.columns:
        df = df.sort_values(by=sort_by, ascending=ascending, na_position="last")

    return df.head(limit).reset_index(drop=True)


_CRITERIA_DISPATCH: dict[str, tuple[str, Callable[[Any, Any], bool]]] = {
    "pe_lt": ("pe_ratio", op_module.lt),
    "pe_gt": ("pe_ratio", op_module.gt),
    "pb_lt": ("pb_ratio", op_module.lt),
    "roe_gt": ("roe", op_module.gt),
    "roa_gt": ("roa", op_module.gt),
    "debt_equity_lt": ("debt_equity", op_module.lt),
    "mcap_gt": ("market_cap", op_module.gt),
    "mcap_lt": ("market_cap", op_module.lt),
    "volume_gt": ("volume", op_module.gt),
    "dividend_yield_gt": ("dividend_yield", op_module.gt),
    "revenue_growth_gt": ("revenue_growth", op_module.gt),
    "eps_growth_gt": ("eps_growth", op_module.gt),
    "rsi_lt": ("rsi", op_module.lt),
    "rsi_gt": ("rsi", op_module.gt),
    "beta_lt": ("beta", op_module.lt),
}


def _apply_criteria(df: pd.DataFrame, criteria: dict[str, Any]) -> pd.DataFrame:
    """Apply screening criteria filters to a DataFrame."""
    for key, value in criteria.items():
        try:
            column, oper = _CRITERIA_DISPATCH.get(key, (None, None))
            if column is None:
                logger.warning("Unknown criteria key: %s", key)
                continue
            df = df[oper(df[column], value)]
        except Exception as exc:
            logger.warning("Failed to apply criteria %s: %s", key, exc)
    return df

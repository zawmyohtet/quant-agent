"""Shared synthetic data provider for market-analysis tool tests."""
from __future__ import annotations

import numpy as np
import pandas as pd

from quantagent.tools.providers.base import AbstractDataProvider


def make_ohlcv(
    close: list[float] | np.ndarray,
    volume: list[float] | np.ndarray | None = None,
    start: str = "2023-06-01",
) -> pd.DataFrame:
    """Build an OHLCV frame from a close series (business-day UTC index)."""
    close_arr = np.asarray(close, dtype=float)
    n = len(close_arr)
    volume_arr = np.asarray(
        volume if volume is not None else [1_000_000.0] * n, dtype=float
    )
    dates = pd.bdate_range(start, periods=n, tz="UTC")
    return pd.DataFrame(
        {
            "Open": close_arr,
            "High": close_arr * 1.01,
            "Low": close_arr * 0.99,
            "Close": close_arr,
            "Volume": volume_arr,
        },
        index=dates,
    )


def trend_close(
    n: int = 300,
    drift: float = 0.0,
    start: float = 100.0,
    seed: int | None = None,
) -> np.ndarray:
    """Geometric close series with optional per-symbol noise."""
    if seed is None:
        return start * (1 + drift) ** np.arange(n)
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, 0.005, n)
    return start * np.cumprod(1 + rets)


class SyntheticProvider(AbstractDataProvider):
    """Provider serving canned frames/classifications; batch uses base defaults."""

    def __init__(
        self,
        frames: dict[str, pd.DataFrame],
        classifications: dict[str, dict] | None = None,
    ) -> None:
        self.frames = frames
        self.classifications = classifications or {}
        self.classification_calls = 0

    async def get_ohlcv(
        self, symbol: str, period: str = "1y", interval: str = "1d"
    ) -> pd.DataFrame:
        if symbol not in self.frames:
            raise ValueError(f"No data for {symbol}")
        return self.frames[symbol]

    async def get_industry_classification(self, symbol: str) -> dict:
        self.classification_calls += 1
        return self.classifications.get(
            symbol, {"symbol": symbol, "sector": None, "industry": None}
        )

    async def get_quote(self, symbol: str) -> dict:
        return {"symbol": symbol, "price": 100.0}

    async def get_fundamentals(self, symbol: str) -> dict:
        return {}

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

"""Tests for the market overview summary."""
from __future__ import annotations

import numpy as np
import pandas as pd
from _synthetic import SyntheticProvider, make_ohlcv, trend_close

from quantagent.tools.market_overview import get_market_summary
from quantagent.tools.universe import SECTOR_ETFS


def _full_market_provider() -> SyntheticProvider:
    frames: dict[str, pd.DataFrame] = {}
    for i, sym in enumerate(
        ["SPY", "QQQ", "DIA", "IWM", "RSP", "XLY", "XLP", "TLT", "HYG", "LQD"]
    ):
        frames[sym] = make_ohlcv(trend_close(n=300, drift=0.001, seed=i))
    for i, etf in enumerate(SECTOR_ETFS.values()):
        frames.setdefault(etf, make_ohlcv(trend_close(n=300, drift=0.001, seed=100 + i)))
    frames["^VIX"] = make_ohlcv(np.full(120, 14.0))
    return SyntheticProvider(frames)


async def test_market_summary_structure() -> None:
    result = await get_market_summary(_full_market_provider())
    assert set(result) == {
        "as_of", "indices", "timing", "breadth", "regime",
        "recommended_exposure", "key_levels",
    }
    assert set(result["indices"]) == {"SPY", "QQQ", "DIA", "IWM"}
    spy = result["indices"]["SPY"]
    assert spy["trend"] in {"up", "down", "mixed"}
    assert spy["price"] > 0
    assert result["timing"]["distribution_days"]["signal"] in {
        "healthy", "caution", "under-pressure",
    }
    assert result["timing"]["follow_through"]["status"] in {
        "confirmed-uptrend", "rally-attempt", "correction",
    }
    assert {"min_pct", "max_pct", "label"} <= set(result["recommended_exposure"])
    assert "support" in result["key_levels"]


async def test_market_summary_skips_missing_index() -> None:
    provider = _full_market_provider()
    del provider.frames["DIA"]
    result = await get_market_summary(provider)
    assert "DIA" not in result["indices"]
    assert "SPY" in result["indices"]

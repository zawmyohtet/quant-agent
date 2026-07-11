"""Tests for the market overview tools."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from _synthetic import SyntheticProvider, make_ohlcv, trend_close

from quantagent.tools import breadth_store as breadth_store_mod
from quantagent.tools.market_overview import (
    generate_market_heatmap,
    get_market_summary,
    get_most_active,
    get_top_movers,
)
from quantagent.tools.technical import wilder_rsi
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
    frames["^VIX3M"] = make_ohlcv(np.full(120, 17.0))
    return SyntheticProvider(frames)


async def test_market_summary_structure() -> None:
    result = await get_market_summary(_full_market_provider())
    assert set(result) == {
        "as_of", "indices", "timing", "breadth", "sentiment", "regime",
        "recommended_exposure", "key_levels",
    }
    assert isinstance(result["sentiment"]["score"], float)
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


# ── Universe-scale functions (deep path) ─────────────────────────────────────


def _mover_provider(monkeypatch: pytest.MonkeyPatch) -> SyntheticProvider:
    """Fake sp500 universe with distinct drifts and one volume spike."""
    symbols = ["UP2", "UP1", "FLAT", "DN1"]
    monkeypatch.setattr(breadth_store_mod, "load_universe", lambda name: symbols)
    drifts = {"UP2": 0.004, "UP1": 0.002, "FLAT": 0.0, "DN1": -0.003}
    frames = {}
    for sym, drift in drifts.items():
        volume = np.full(300, 1_000_000.0)
        if sym == "FLAT":
            volume[-1] = 5_000_000.0
        frames[sym] = make_ohlcv(trend_close(n=300, drift=drift), volume)
    classifications = {
        "UP2": {"symbol": "UP2", "sector": "Technology", "industry": "Software"},
        "UP1": {"symbol": "UP1", "sector": "Technology", "industry": "Hardware"},
        "FLAT": {"symbol": "FLAT", "sector": "Utilities", "industry": "Electric"},
        "DN1": {"symbol": "DN1", "sector": "Utilities", "industry": "Gas"},
    }
    return SyntheticProvider(frames, classifications=classifications)


async def test_top_movers_up_and_down(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _mover_provider(monkeypatch)
    up = await get_top_movers(provider, universe="sp500", count=2)
    assert up["symbol"].tolist() == ["UP2", "UP1"]
    assert (up["change_pct"] > 0).all()
    down = await get_top_movers(provider, universe="sp500", direction="down", count=1)
    assert down["symbol"].tolist() == ["DN1"]


async def test_top_movers_weekly_period(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _mover_provider(monkeypatch)
    df = await get_top_movers(provider, universe="sp500", period="1w", count=4)
    assert df.iloc[0]["symbol"] == "UP2"
    assert df.iloc[0]["change_pct"] > df.iloc[1]["change_pct"]


async def test_most_active_finds_volume_spike(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _mover_provider(monkeypatch)
    df = await get_most_active(provider, universe="sp500", count=2)
    assert df.iloc[0]["symbol"] == "FLAT"
    assert df.iloc[0]["volume_ratio"] > 4


async def test_heatmap_grouped_by_sector(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _mover_provider(monkeypatch)
    result = await generate_market_heatmap(provider, universe="sp500")
    assert result["group_by"] == "sector"
    assert set(result["groups"]) == {"Technology", "Utilities"}
    software = result["groups"]["Technology"]["Software"]
    assert "UP2" in software
    assert {"value", "size"} <= set(software["UP2"])


async def test_heatmap_grouped_by_industry(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _mover_provider(monkeypatch)
    result = await generate_market_heatmap(
        provider, universe="sp500", metric="rsi", group_by="industry"
    )
    assert "Software" in result["groups"]


async def test_heatmap_rejects_unknown_group(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _mover_provider(monkeypatch)
    with pytest.raises(ValueError):
        await generate_market_heatmap(provider, universe="sp500", group_by="bogus")


def test_wilder_rsi_extremes() -> None:
    rising = pd.Series([100.0 + i for i in range(30)])
    falling = pd.Series([100.0 - i for i in range(30)])
    assert wilder_rsi(rising) == 100.0
    assert wilder_rsi(falling) < 10
    assert wilder_rsi(pd.Series([100.0] * 5)) is None

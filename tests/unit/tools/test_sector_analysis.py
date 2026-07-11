"""Tests for sector and industry analysis tools."""
from __future__ import annotations

import pandas as pd
import pytest
from _synthetic import SyntheticProvider, make_ohlcv, trend_close

from quantagent.tools.sector_analysis import (
    _rs_trend,
    compute_sector_correlation,
    compute_sector_relative_strength,
    detect_sector_rotation,
    get_industry_performance,
    get_sector_etf_heatmap,
    get_sector_performance_ranked,
)
from quantagent.tools.universe import SECTOR_ETFS


def _sector_provider(extra: dict[str, pd.DataFrame] | None = None) -> SyntheticProvider:
    """XLK strongly rising, XLU strongly falling, the rest mildly mixed."""
    drifts = {"XLK": 0.003, "XLU": -0.003}
    frames = {}
    for i, etf in enumerate(SECTOR_ETFS.values()):
        drift = drifts.get(etf, 0.0005 if i % 2 == 0 else -0.0005)
        frames[etf] = make_ohlcv(trend_close(n=300, drift=drift, seed=i))
    frames["SPY"] = make_ohlcv(trend_close(n=300, drift=0.0005, seed=99))
    frames.update(extra or {})
    return SyntheticProvider(frames)


async def test_performance_ranked_orders_by_rank() -> None:
    df = await get_sector_performance_ranked(_sector_provider())
    assert len(df) == 11
    assert df.iloc[0]["sector"] == "Technology"
    assert df.iloc[-1]["sector"] == "Utilities"
    assert df["rank"].tolist() == list(range(1, 12))
    for col in ["1d", "1w", "1m", "3m", "6m", "1y"]:
        assert col in df.columns


async def test_performance_ranked_custom_periods() -> None:
    df = await get_sector_performance_ranked(_sector_provider(), periods=["1m", "3m"])
    assert "1m" in df.columns
    assert "1y" not in df.columns


async def test_relative_strength_ranks_leader_first() -> None:
    df = await compute_sector_relative_strength(_sector_provider())
    assert df.iloc[0]["sector"] == "Technology"
    assert df.iloc[0]["rs_ratio"] > 1
    assert df.iloc[-1]["sector"] == "Utilities"
    assert df.iloc[-1]["rs_ratio"] < 1
    assert set(df["trend"]).issubset({"improving", "deteriorating", "neutral"})


async def test_relative_strength_sector_filter() -> None:
    df = await compute_sector_relative_strength(
        _sector_provider(), sectors=["Technology", "Utilities"]
    )
    assert set(df["sector"]) == {"Technology", "Utilities"}


def test_rs_trend_improving() -> None:
    # Rise must begin inside the RS window so RS now exceeds RS 21 sessions ago.
    flat_then_up = [100.0] * 250 + list(trend_close(n=50, drift=0.005, start=100.0))
    bench = [100.0] * 300
    close = pd.Series(flat_then_up)
    assert _rs_trend(close, pd.Series(bench), 63) == "improving"


async def test_sector_rotation_risk_on() -> None:
    result = await detect_sector_rotation(_sector_provider())
    assert result["rotation_signal"] in {"risk-on", "risk-off", "neutral"}
    assert "Technology" in result["leading_sectors"]
    assert "Utilities" in result["lagging_sectors"]
    assert result["cycle_phase"] in {
        "early-recovery", "mid-expansion", "late-cycle", "recession",
    }


async def test_sector_rotation_missing_benchmark() -> None:
    frames = {etf: make_ohlcv(trend_close(n=300)) for etf in SECTOR_ETFS.values()}
    result = await detect_sector_rotation(SyntheticProvider(frames))
    assert "error" in result


async def test_heatmap_metrics() -> None:
    provider = _sector_provider()
    for metric in ["performance", "volume", "volatility", "rsi"]:
        result = await get_sector_etf_heatmap(provider, metric=metric)
        assert result["metric"] == metric
        assert len(result["sectors"]) == 11
        values = [v["value"] for v in result["sectors"].values()]
        assert any(v is not None for v in values)


async def test_heatmap_unknown_metric() -> None:
    with pytest.raises(ValueError):
        await get_sector_etf_heatmap(_sector_provider(), metric="bogus")


async def test_sector_correlation_shape() -> None:
    corr = await compute_sector_correlation(_sector_provider())
    assert corr.shape == (11, 11)
    assert (corr.values.diagonal() == 1.0).all()


async def test_industry_performance_groups_and_ranks() -> None:
    classifications = {
        "AAA": {"symbol": "AAA", "sector": "Technology", "industry": "Software"},
        "BBB": {"symbol": "BBB", "sector": "Technology", "industry": "Software"},
        "CCC": {"symbol": "CCC", "sector": "Technology", "industry": "Semiconductors"},
        "DDD": {"symbol": "DDD", "sector": "Healthcare", "industry": "Biotech"},
    }
    frames = {
        "AAA": make_ohlcv(trend_close(n=150, drift=0.001)),
        "BBB": make_ohlcv(trend_close(n=150, drift=0.002)),
        "CCC": make_ohlcv(trend_close(n=150, drift=0.004)),
        "DDD": make_ohlcv(trend_close(n=150, drift=0.001)),
    }
    provider = SyntheticProvider(frames, classifications=classifications)
    df = await get_industry_performance(
        provider, "Technology", symbols=["AAA", "BBB", "CCC", "DDD"]
    )
    assert set(df["industry"]) == {"Software", "Semiconductors"}
    assert df.iloc[0]["industry"] == "Semiconductors"
    software = df[df["industry"] == "Software"].iloc[0]
    assert software["n_stocks"] == 2


async def test_industry_performance_uses_classification_cache() -> None:
    classifications = {
        "AAA": {"symbol": "AAA", "sector": "Technology", "industry": "Software"},
    }
    frames = {"AAA": make_ohlcv(trend_close(n=150, drift=0.001))}
    provider = SyntheticProvider(frames, classifications=classifications)
    await get_industry_performance(provider, "Technology", symbols=["AAA"])
    first_calls = provider.classification_calls
    await get_industry_performance(provider, "Technology", symbols=["AAA"])
    assert provider.classification_calls == first_calls  # served from cache


async def test_industry_performance_no_members() -> None:
    provider = SyntheticProvider({}, classifications={})
    df = await get_industry_performance(provider, "Technology", symbols=["ZZZ"])
    assert df.empty

"""Tests for market breadth, timing, and regime tools."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from _synthetic import SyntheticProvider, make_ohlcv, trend_close

from quantagent.tools import breadth_store as breadth_store_mod
from quantagent.tools.market_breadth import (
    _CROSS_ASSET_TICKERS,
    _pct_above,
    _regime_from_score,
    _sentiment_label,
    _thrust_signal,
    _vix_score,
    compute_advance_decline,
    compute_breadth_thrust,
    compute_market_sentiment,
    compute_new_highs_lows,
    compute_percent_above_ma,
    count_distribution_days,
    detect_follow_through_day,
    detect_market_regime,
)
from quantagent.tools.universe import SECTOR_ETFS

# ── Distribution days ────────────────────────────────────────────────────────


def _distribution_frame(n_dist: int) -> pd.DataFrame:
    """Flat series with n_dist crafted distribution days in the last 25 sessions."""
    n = 120
    close = np.full(n, 100.0)
    volume = np.full(n, 1_000_000.0)
    for i in range(n_dist):
        pos = n - 20 + i * 3
        close[pos:] = close[pos - 1] * 0.99  # -1% drop that persists
        volume[pos] = volume[pos - 1] * 1.5
    return make_ohlcv(close, volume)


async def test_count_distribution_days_detects_crafted_days() -> None:
    provider = SyntheticProvider({"SPY": _distribution_frame(3)})
    result = await count_distribution_days(provider)
    assert result["count"] == 3
    assert result["signal"] == "caution"
    assert len(result["dates"]) == 3


async def test_count_distribution_days_healthy_when_none() -> None:
    provider = SyntheticProvider({"SPY": _distribution_frame(0)})
    result = await count_distribution_days(provider)
    assert result["count"] == 0
    assert result["signal"] == "healthy"


async def test_count_distribution_days_under_pressure() -> None:
    provider = SyntheticProvider({"SPY": _distribution_frame(5)})
    result = await count_distribution_days(provider)
    assert result["count"] == 5
    assert result["signal"] == "under-pressure"


# ── Follow-through day ───────────────────────────────────────────────────────


def _ftd_frame(with_ftd: bool, rally_days: int = 8) -> pd.DataFrame:
    """Decline into a low, then a rally; optionally a +2% high-volume day 5."""
    decline = [100.0 * (0.99**i) for i in range(40)]
    low = decline[-1]
    rally_rets = [0.004] * rally_days
    if with_ftd:
        rally_rets[4] = 0.02
    rally = list(np.array(low) * np.cumprod(1 + np.array(rally_rets)))
    close = decline + rally
    volume = [1_000_000.0] * len(close)
    if with_ftd:
        volume[40 + 4] = 2_000_000.0
    return make_ohlcv(close, volume)


async def test_ftd_detected() -> None:
    provider = SyntheticProvider({"SPY": _ftd_frame(with_ftd=True)})
    result = await detect_follow_through_day(provider)
    assert result["ftd_detected"] is True
    assert result["status"] == "confirmed-uptrend"
    assert result["ftd_date"] is not None


async def test_rally_attempt_without_ftd() -> None:
    provider = SyntheticProvider({"SPY": _ftd_frame(with_ftd=False)})
    result = await detect_follow_through_day(provider)
    assert result["ftd_detected"] is False
    assert result["status"] == "rally-attempt"


async def test_correction_when_no_rally() -> None:
    close = [100.0 * (0.995**i) for i in range(80)]
    provider = SyntheticProvider({"SPY": make_ohlcv(close)})
    result = await detect_follow_through_day(provider)
    assert result["ftd_detected"] is False
    assert result["status"] == "correction"
    assert result["rally_day"] == 0


# ── Percent above MA ─────────────────────────────────────────────────────────


def _sector_frames(n_rising: int) -> dict[str, pd.DataFrame]:
    frames = {}
    for i, etf in enumerate(SECTOR_ETFS.values()):
        drift = 0.002 if i < n_rising else -0.002
        frames[etf] = make_ohlcv(trend_close(n=300, drift=drift))
    return frames


async def test_percent_above_ma_counts_rising_etfs() -> None:
    provider = SyntheticProvider(_sector_frames(n_rising=6))
    result = await compute_percent_above_ma(provider)
    assert result["proxy"] is False
    assert result["n_symbols"] == 11
    assert result["pct_above"][50] == round(6 / 11 * 100, 2)


async def test_percent_above_ma_flags_proxy_for_other_universe() -> None:
    provider = SyntheticProvider(_sector_frames(n_rising=6))
    result = await compute_percent_above_ma(provider, universe="sp500")
    assert result["proxy"] is True


def test_pct_above_empty() -> None:
    assert _pct_above([], 50) is None


# ── Market regime ────────────────────────────────────────────────────────────


def _regime_frames(bullish: bool) -> dict[str, pd.DataFrame]:
    """Cross-asset + sector frames with all components aligned one way."""
    strong, weak = (0.002, -0.002) if bullish else (-0.002, 0.002)
    frames: dict[str, pd.DataFrame] = {
        "SPY": make_ohlcv(trend_close(drift=strong)),
        "RSP": make_ohlcv(trend_close(drift=strong * 1.5)),
        "IWM": make_ohlcv(trend_close(drift=strong * 1.5)),
        "XLY": make_ohlcv(trend_close(drift=strong * 1.5)),
        "XLP": make_ohlcv(trend_close(drift=weak)),
        "TLT": make_ohlcv(trend_close(drift=weak)),
        "HYG": make_ohlcv(trend_close(drift=strong)),
        "LQD": make_ohlcv(trend_close(drift=weak)),
        "^VIX": make_ohlcv(np.full(120, 12.0 if bullish else 38.0)),
    }
    for etf in SECTOR_ETFS.values():
        frames.setdefault(etf, make_ohlcv(trend_close(drift=strong)))
    return frames


async def test_regime_bullish() -> None:
    provider = SyntheticProvider(_regime_frames(bullish=True))
    result = await detect_market_regime(provider)
    assert result["regime"] in {"bull", "strong-bull"}
    assert result["recommended_exposure"]["min_pct"] >= 70
    assert result["confidence"] > 0.5
    assert result["components"]["trend_direction"] == "uptrend"


async def test_regime_bearish() -> None:
    provider = SyntheticProvider(_regime_frames(bullish=False))
    result = await detect_market_regime(provider)
    assert result["regime"] in {"bear", "strong-bear"}
    assert result["recommended_exposure"]["max_pct"] <= 60
    assert result["components"]["trend_direction"] == "downtrend"


async def test_regime_survives_missing_vix() -> None:
    frames = _regime_frames(bullish=True)
    del frames["^VIX"]
    provider = SyntheticProvider(frames)
    result = await detect_market_regime(provider)
    assert result["components"]["volatility_regime"] == "unavailable"
    assert result["regime"] in {"bull", "strong-bull"}


def test_regime_bands_cover_all_scores() -> None:
    assert _regime_from_score(95)[0] == "strong-bull"
    assert _regime_from_score(70)[0] == "bull"
    assert _regime_from_score(50)[0] == "neutral"
    assert _regime_from_score(30)[0] == "bear"
    assert _regime_from_score(5)[0] == "strong-bear"


def test_vix_score_bands() -> None:
    assert _vix_score(12.0) == 1.0
    assert _vix_score(18.0) == 0.5
    assert _vix_score(22.0) == 0.0
    assert _vix_score(28.0) == -0.5
    assert _vix_score(40.0) == -1.0
    assert _vix_score(None) == 0.0


def test_cross_asset_tickers_complete() -> None:
    assert set(_CROSS_ASSET_TICKERS.values()) == {
        "SPY", "RSP", "IWM", "XLY", "XLP", "TLT", "HYG", "LQD",
    }


# ── Deep-path breadth (universe store) ───────────────────────────────────────


def _mixed_universe_provider(monkeypatch: pytest.MonkeyPatch) -> SyntheticProvider:
    """Fake sp500 universe of 6 rising + 5 falling symbols (+ ETF proxies)."""
    symbols = [f"S{i}" for i in range(11)]
    monkeypatch.setattr(breadth_store_mod, "load_universe", lambda name: symbols)
    frames = {
        sym: make_ohlcv(trend_close(n=300, drift=0.002 if i < 6 else -0.002))
        for i, sym in enumerate(symbols)
    }
    for i, etf in enumerate(SECTOR_ETFS.values()):
        frames[etf] = make_ohlcv(trend_close(n=300, drift=0.001, seed=i))
    return SyntheticProvider(frames)


async def test_advance_decline_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _mixed_universe_provider(monkeypatch)
    df = await compute_advance_decline(provider, universe="sp500", period="1m")
    assert len(df) == 21
    assert (df["Advancing"] == 6).all()
    assert (df["Declining"] == 5).all()
    assert (df["NetAdvancing"] == 1).all()
    assert df["ADLine"].is_monotonic_increasing


async def test_new_highs_lows_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _mixed_universe_provider(monkeypatch)
    df = await compute_new_highs_lows(provider, universe="sp500", period="1m")
    assert (df["NewHighs"] == 6).all()
    assert (df["NewLows"] == 5).all()
    assert (df["NetNewHighs"] == 1).all()
    assert df["HighLowRatio"].iloc[-1] == round(6 / 11, 4)


async def test_breadth_thrust_turns_bullish(monkeypatch: pytest.MonkeyPatch) -> None:
    symbols = [f"S{i}" for i in range(11)]
    monkeypatch.setattr(breadth_store_mod, "load_universe", lambda name: symbols)
    # All symbols decline for 270 sessions, then rally for the last 30.
    close = list(trend_close(n=270, drift=-0.001)) + list(
        trend_close(n=30, drift=0.003, start=76.0)
    )
    frames = {sym: make_ohlcv([c * (1 + i * 0.01) for c in close]) for i, sym in enumerate(symbols)}
    provider = SyntheticProvider(frames)
    result = await compute_breadth_thrust(provider, universe="sp500", period="3m")
    assert result["thrust_value"] > 50
    assert result["thrust_signal"] == "bullish"
    assert not result["history"].empty


def test_thrust_signal_bands() -> None:
    assert _thrust_signal(80.0) == "bullish"
    assert _thrust_signal(-80.0) == "bearish"
    assert _thrust_signal(0.0) == "neutral"


async def test_percent_above_ma_deep_path(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _mixed_universe_provider(monkeypatch)
    result = await compute_percent_above_ma(provider, universe="sp500", allow_warmup=True)
    assert result["proxy"] is False
    assert result["n_symbols"] == 11
    assert result["pct_above"][50] == round(6 / 11 * 100, 2)


async def test_regime_uses_warm_universe_store(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _mixed_universe_provider(monkeypatch)
    frames = _regime_frames(bullish=True)
    provider.frames.update(frames)
    # Warm the sp500 store first, then regime should report the universe source.
    await compute_percent_above_ma(provider, universe="sp500", allow_warmup=True)
    result = await detect_market_regime(provider, universe="sp500")
    assert result["components"]["breadth_source"] == "universe:sp500"


# ── Sentiment ────────────────────────────────────────────────────────────────


def _sentiment_provider(bullish: bool) -> SyntheticProvider:
    frames = _regime_frames(bullish=bullish)
    frames["^VIX3M"] = make_ohlcv(np.full(80, 17.0 if bullish else 30.0))
    return SyntheticProvider(frames)


async def test_sentiment_bullish() -> None:
    result = await compute_market_sentiment(_sentiment_provider(bullish=True))
    assert result["score"] > 20
    assert result["label"] in {"greed", "extreme-greed"}
    assert result["components"]["vix_term_structure"] == "contango"
    assert result["components"]["put_call_ratio"] is None


async def test_sentiment_bearish() -> None:
    result = await compute_market_sentiment(_sentiment_provider(bullish=False))
    assert result["score"] < -20
    assert result["label"] in {"fear", "extreme-fear"}
    assert result["components"]["vix_term_structure"] == "backwardation"


async def test_sentiment_survives_missing_series() -> None:
    frames = _regime_frames(bullish=True)
    del frames["^VIX"]
    result = await compute_market_sentiment(SyntheticProvider(frames))
    assert result["components"]["vix_level"] is None
    assert result["components"]["vix_term_structure"] is None
    assert isinstance(result["score"], float)


def test_sentiment_label_bands() -> None:
    assert _sentiment_label(75.0) == "extreme-greed"
    assert _sentiment_label(30.0) == "greed"
    assert _sentiment_label(0.0) == "neutral"
    assert _sentiment_label(-30.0) == "fear"
    assert _sentiment_label(-75.0) == "extreme-fear"

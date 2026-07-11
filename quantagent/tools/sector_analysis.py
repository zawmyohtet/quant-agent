"""Sector and industry analysis tool functions.

Fast-path market analysis built on the 11 SPDR sector ETFs — every
function here works on the free tier from a single batch download.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import pandas as pd

from quantagent.tools.cache import DataCache
from quantagent.tools.providers.base import AbstractDataProvider
from quantagent.tools.technical import compute_indicators
from quantagent.tools.universe import CYCLICAL_SECTORS, DEFENSIVE_SECTORS, SECTOR_ETFS

logger = logging.getLogger(__name__)

_PERIOD_DAYS: dict[str, int] = {
    "1d": 1,
    "1w": 5,
    "1m": 21,
    "3m": 63,
    "6m": 126,
    "1y": 252,
}

_DEFAULT_PERIODS = ["1d", "1w", "1m", "3m", "6m", "1y"]

# Sectors that historically lead each economic cycle phase.
_CYCLE_PHASE_LEADERS: dict[str, frozenset[str]] = {
    "early-recovery": frozenset(
        {"Financials", "Consumer Discretionary", "Real Estate", "Industrials"}
    ),
    "mid-expansion": frozenset(
        {"Technology", "Communication Services", "Industrials"}
    ),
    "late-cycle": frozenset(
        {"Energy", "Materials", "Consumer Staples", "Healthcare"}
    ),
    "recession": frozenset({"Utilities", "Consumer Staples", "Healthcare"}),
}

_CLASSIFICATION_TTL_SEC = 7 * 24 * 3600


def _period_return(close: pd.Series, days: int) -> float | None:
    """Return the pct change over the trailing ``days`` sessions."""
    if len(close) <= days:
        return None
    return round(float(close.iloc[-1] / close.iloc[-(days + 1)] - 1), 4)


async def _fetch_sector_frames(
    provider: AbstractDataProvider, extra: list[str] | None = None
) -> dict[str, pd.DataFrame]:
    """Batch-fetch 2y daily OHLCV for all sector ETFs plus ``extra`` symbols."""
    symbols = list(SECTOR_ETFS.values()) + (extra or [])
    return await provider.get_batch_ohlcv(symbols, period="2y")


async def get_sector_performance_ranked(
    provider: AbstractDataProvider,
    periods: list[str] | None = None,
) -> pd.DataFrame:
    """Rank all GICS sectors by performance across multiple timeframes.

    Args:
        provider: Market data provider.
        periods: Timeframes to include, from 1d/1w/1m/3m/6m/1y.

    Returns:
        DataFrame with columns: sector, etf, one column per period (pct
        return as decimal), and rank (1 = best average rank across periods).
    """
    periods = periods or _DEFAULT_PERIODS
    frames = await _fetch_sector_frames(provider)
    rows = []
    for sector, etf in SECTOR_ETFS.items():
        df = frames.get(etf)
        if df is None or df.empty:
            continue
        row: dict = {"sector": sector, "etf": etf}
        for p in periods:
            row[p] = _period_return(df["Close"], _PERIOD_DAYS[p])
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    result = pd.DataFrame(rows)
    avg_rank = result[periods].rank(ascending=False).mean(axis=1)
    result["rank"] = avg_rank.rank(method="first").astype(int)
    return result.sort_values("rank").reset_index(drop=True)


async def get_industry_performance(
    provider: AbstractDataProvider,
    sector: str,
    symbols: list[str] | None = None,
) -> pd.DataFrame:
    """Rank industries within a sector by performance.

    Classifies each symbol via the provider (cached for 7 days), keeps
    those in ``sector``, and aggregates 1m/3m returns by industry.
    Warning: on a cold cache this classifies the whole universe and can
    take minutes on free-tier providers.

    Args:
        provider: Market data provider.
        sector: Sector name to drill into (provider taxonomy, e.g. "Technology").
        symbols: Universe to classify; defaults to the S&P 500 constituents.

    Returns:
        DataFrame with columns: industry, n_stocks, 1m, 3m, rank.
    """
    if symbols is None:
        from quantagent.tools.screener import _fetch_universe_tickers

        symbols = _fetch_universe_tickers("sp500")
    classifications = await _classify_symbols(provider, symbols)
    members = [
        s for s, c in classifications.items()
        if (c.get("sector") or "").lower() == sector.lower() and c.get("industry")
    ]
    if not members:
        return pd.DataFrame()
    frames = await provider.get_batch_ohlcv(members, period="6mo")
    return _aggregate_industry_returns(frames, classifications)


async def _classify_symbols(
    provider: AbstractDataProvider, symbols: list[str]
) -> dict[str, dict]:
    """Classify symbols into sector/industry with caching and bounded concurrency."""
    cache = DataCache()
    results: dict[str, dict] = {}
    semaphore = asyncio.Semaphore(8)

    async def _classify(sym: str) -> None:
        key = f"classification:{sym}"
        cached = await cache.get(key)
        if cached is not None:
            results[sym] = cached
            return
        async with semaphore:
            try:
                info = await provider.get_industry_classification(sym)
            except Exception as exc:
                logger.warning("Classification failed for %s: %s", sym, exc)
                return
        results[sym] = info
        await cache.set(key, info, ttl=_CLASSIFICATION_TTL_SEC)

    async with asyncio.TaskGroup() as tg:
        for sym in symbols:
            tg.create_task(_classify(sym))
    return results


def _aggregate_industry_returns(
    frames: dict[str, pd.DataFrame], classifications: dict[str, dict]
) -> pd.DataFrame:
    """Aggregate per-symbol 1m/3m returns into industry-level means."""
    rows = []
    for sym, df in frames.items():
        if df.empty:
            continue
        rows.append(
            {
                "industry": classifications[sym]["industry"],
                "1m": _period_return(df["Close"], _PERIOD_DAYS["1m"]),
                "3m": _period_return(df["Close"], _PERIOD_DAYS["3m"]),
            }
        )
    if not rows:
        return pd.DataFrame()
    grouped = (
        pd.DataFrame(rows)
        .groupby("industry")
        .agg(n_stocks=("industry", "size"), **{"1m": ("1m", "mean"), "3m": ("3m", "mean")})
        .reset_index()
    )
    grouped[["1m", "3m"]] = grouped[["1m", "3m"]].round(4)
    grouped["rank"] = grouped["3m"].rank(ascending=False, method="first").astype(int)
    return grouped.sort_values("rank").reset_index(drop=True)


def _relative_strength(
    close: pd.Series, bench: pd.Series, days: int
) -> float | None:
    """RS ratio: symbol return over window divided by benchmark return."""
    if len(close) <= days or len(bench) <= days:
        return None
    sym_ret = float(close.iloc[-1] / close.iloc[-(days + 1)])
    bench_ret = float(bench.iloc[-1] / bench.iloc[-(days + 1)])
    if bench_ret == 0:
        return None
    return round(sym_ret / bench_ret, 4)


def _rs_trend(close: pd.Series, bench: pd.Series, days: int) -> str:
    """Classify RS momentum by comparing current RS to RS 21 sessions ago."""
    rs_now = _relative_strength(close, bench, days)
    rs_prev = _relative_strength(close.iloc[:-21], bench.iloc[:-21], days)
    if rs_now is None or rs_prev is None:
        return "neutral"
    delta = rs_now - rs_prev
    if delta > 0.01:
        return "improving"
    if delta < -0.01:
        return "deteriorating"
    return "neutral"


async def compute_sector_relative_strength(
    provider: AbstractDataProvider,
    sectors: list[str] | None = None,
    benchmark: str = "SPY",
    period: str = "3m",
) -> pd.DataFrame:
    """Compute relative strength of each sector vs a benchmark.

    Args:
        provider: Market data provider.
        sectors: Sector names to include (default: all 11).
        benchmark: Benchmark symbol (default SPY).
        period: RS window — 1w, 1m, 3m, 6m, or 1y.

    Returns:
        DataFrame with columns: sector, etf, rs_ratio (>1 = outperforming),
        rs_rank, trend (improving/deteriorating/neutral).
    """
    days = _PERIOD_DAYS[period]
    selected = {s: e for s, e in SECTOR_ETFS.items() if sectors is None or s in sectors}
    frames = await _fetch_sector_frames(provider, extra=[benchmark])
    bench_df = frames.get(benchmark)
    if bench_df is None or bench_df.empty:
        return pd.DataFrame()
    bench_close = bench_df["Close"]
    rows = []
    for sector, etf in selected.items():
        df = frames.get(etf)
        if df is None or df.empty:
            continue
        rs = _relative_strength(df["Close"], bench_close, days)
        if rs is None:
            continue
        rows.append(
            {
                "sector": sector,
                "etf": etf,
                "rs_ratio": rs,
                "trend": _rs_trend(df["Close"], bench_close, days),
            }
        )
    if not rows:
        return pd.DataFrame()
    result = pd.DataFrame(rows)
    result["rs_rank"] = result["rs_ratio"].rank(ascending=False, method="first").astype(int)
    return result.sort_values("rs_rank").reset_index(drop=True)


async def detect_sector_rotation(
    provider: AbstractDataProvider,
    lookback_days: int = 90,
) -> dict:
    """Detect sector rotation patterns using relative strength momentum.

    Args:
        provider: Market data provider.
        lookback_days: RS window in calendar sessions (default 90).

    Returns:
        Dict with leading_sectors, lagging_sectors, improving_sectors,
        deteriorating_sectors, rotation_signal (risk-on/risk-off/neutral),
        and cycle_phase (early-recovery/mid-expansion/late-cycle/recession).
    """
    frames = await _fetch_sector_frames(provider, extra=["SPY"])
    bench = frames.get("SPY")
    if bench is None or bench.empty:
        return {"error": "benchmark data unavailable"}
    stats = _sector_rs_stats(frames, bench["Close"], lookback_days)
    if not stats:
        return {"error": "sector data unavailable"}
    ranked = sorted(stats, key=lambda s: s["rs"], reverse=True)
    improving = [s["sector"] for s in stats if s["momentum"] > 0.02]
    deteriorating = [s["sector"] for s in stats if s["momentum"] < -0.02]
    leading = [s["sector"] for s in ranked[:3]]
    return {
        "leading_sectors": leading,
        "lagging_sectors": [s["sector"] for s in ranked[-3:]],
        "improving_sectors": improving,
        "deteriorating_sectors": deteriorating,
        "rotation_signal": _rotation_signal(stats),
        "cycle_phase": _cycle_phase(set(leading) | set(improving)),
        "as_of": datetime.now(UTC).date().isoformat(),
    }


def _sector_rs_stats(
    frames: dict[str, pd.DataFrame], bench_close: pd.Series, lookback_days: int
) -> list[dict]:
    """Per-sector RS ratio and RS momentum (change over half the lookback)."""
    half = max(lookback_days // 2, 1)
    stats = []
    for sector, etf in SECTOR_ETFS.items():
        df = frames.get(etf)
        if df is None or df.empty:
            continue
        rs = _relative_strength(df["Close"], bench_close, lookback_days)
        rs_half_ago = _relative_strength(
            df["Close"].iloc[:-half], bench_close.iloc[:-half], lookback_days
        )
        if rs is None or rs_half_ago is None:
            continue
        stats.append({"sector": sector, "rs": rs, "momentum": round(rs - rs_half_ago, 4)})
    return stats


def _rotation_signal(stats: list[dict]) -> str:
    """Risk-on when cyclical RS momentum leads defensive, risk-off when it lags."""
    cyclical = [s["momentum"] for s in stats if s["sector"] in CYCLICAL_SECTORS]
    defensive = [s["momentum"] for s in stats if s["sector"] in DEFENSIVE_SECTORS]
    if not cyclical or not defensive:
        return "neutral"
    spread = sum(cyclical) / len(cyclical) - sum(defensive) / len(defensive)
    if spread > 0.01:
        return "risk-on"
    if spread < -0.01:
        return "risk-off"
    return "neutral"


def _cycle_phase(strong_sectors: set[str]) -> str:
    """Estimate cycle phase from which phase's leader sectors are strongest."""
    scores = {
        phase: len(strong_sectors & leaders)
        for phase, leaders in _CYCLE_PHASE_LEADERS.items()
    }
    best = max(scores, key=lambda p: (scores[p], p))
    return best if scores[best] > 0 else "mid-expansion"


def _metric_performance(df: pd.DataFrame) -> float | None:
    return _period_return(df["Close"], 1)


def _metric_volume(df: pd.DataFrame) -> float | None:
    vol = df["Volume"]
    if len(vol) < 21:
        return None
    avg = float(vol.iloc[-21:-1].mean())
    return round(float(vol.iloc[-1]) / avg, 4) if avg > 0 else None


def _metric_volatility(df: pd.DataFrame) -> float | None:
    rets = df["Close"].pct_change().iloc[-21:]
    if len(rets.dropna()) < 5:
        return None
    return round(float(rets.std() * (252**0.5)), 4)


def _metric_rsi(df: pd.DataFrame) -> float | None:
    if len(df) < 15:
        return None
    with_rsi = compute_indicators(df, ["rsi_14"])
    value = with_rsi["RSI_14"].iloc[-1]
    return round(float(value), 4) if pd.notna(value) else None


_HEATMAP_METRICS = {
    "performance": _metric_performance,
    "volume": _metric_volume,
    "volatility": _metric_volatility,
    "rsi": _metric_rsi,
}


async def get_sector_etf_heatmap(
    provider: AbstractDataProvider,
    metric: str = "performance",
) -> dict:
    """Generate heatmap data for sector ETFs.

    Args:
        provider: Market data provider.
        metric: performance (1d return) | volume (vs 20d avg) |
            volatility (annualized 21d) | rsi (RSI-14).

    Returns:
        Dict: {metric, as_of, sectors: {sector: {etf, value}}}.
    """
    metric_fn = _HEATMAP_METRICS.get(metric)
    if metric_fn is None:
        raise ValueError(f"Unknown heatmap metric: {metric}")
    frames = await _fetch_sector_frames(provider)
    sectors = {}
    for sector, etf in SECTOR_ETFS.items():
        df = frames.get(etf)
        if df is None or df.empty:
            continue
        sectors[sector] = {"etf": etf, "value": metric_fn(df)}
    return {
        "metric": metric,
        "as_of": datetime.now(UTC).date().isoformat(),
        "sectors": sectors,
    }


async def compute_sector_correlation(
    provider: AbstractDataProvider,
    period: str = "6m",
) -> pd.DataFrame:
    """Correlation matrix of sector ETF daily returns.

    Args:
        provider: Market data provider.
        period: Correlation window — 1m, 3m, 6m, or 1y.

    Returns:
        DataFrame indexed/columned by sector name, values rounded to 4dp.
    """
    days = _PERIOD_DAYS[period]
    frames = await _fetch_sector_frames(provider)
    closes = {
        sector: frames[etf]["Close"].iloc[-(days + 1):]
        for sector, etf in SECTOR_ETFS.items()
        if etf in frames and not frames[etf].empty
    }
    if not closes:
        return pd.DataFrame()
    returns = pd.DataFrame(closes).pct_change().dropna()
    return returns.corr().round(4)

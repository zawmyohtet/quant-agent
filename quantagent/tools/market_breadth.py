"""Market breadth, timing, and regime tool functions.

Two tiers:

- Fast path (index/ETF data only): distribution days, Follow-Through
  Day, sector-ETF breadth proxy, cross-asset regime composite, and
  composite sentiment. Always completes in seconds.
- Deep path (universe-level, backed by the incremental BreadthStore):
  true advance/decline line, new highs/lows, percent above MA, and
  breadth thrust. Slow on first use (cache warm-up), incremental after.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

import pandas as pd

from quantagent.tools.breadth_store import BreadthStore
from quantagent.tools.providers.base import AbstractDataProvider
from quantagent.tools.universe import SECTOR_ETFS

logger = logging.getLogger(__name__)

_HISTORY_DAYS: dict[str, int] = {"1m": 21, "3m": 63, "6m": 126, "1y": 252}

# Cross-asset ratio inputs for regime detection (all free ETF tickers).
_CROSS_ASSET_TICKERS: dict[str, str] = {
    "benchmark": "SPY",
    "equal_weight": "RSP",
    "small_cap": "IWM",
    "cyclical": "XLY",
    "defensive": "XLP",
    "long_bond": "TLT",
    "high_yield": "HYG",
    "invest_grade": "LQD",
}

_VIX_SYMBOL = "^VIX"

# IBD-style thresholds.
_DISTRIBUTION_DAY_LOSS = -0.002  # close down >= 0.2%
_FTD_MIN_GAIN = 0.0125  # follow-through day gains >= 1.25%
_FTD_MIN_RALLY_DAY = 4

# Composite score (0-100) -> regime label and recommended exposure band.
_REGIME_BANDS: list[tuple[float, str, dict]] = [
    (80.0, "strong-bull", {"min_pct": 90, "max_pct": 100, "label": "strong"}),
    (60.0, "bull", {"min_pct": 70, "max_pct": 90, "label": "healthy"}),
    (40.0, "neutral", {"min_pct": 50, "max_pct": 70, "label": "neutral"}),
    (20.0, "bear", {"min_pct": 40, "max_pct": 60, "label": "weakening"}),
    (0.0, "strong-bear", {"min_pct": 25, "max_pct": 40, "label": "critical"}),
]


async def count_distribution_days(
    provider: AbstractDataProvider,
    index_symbol: str = "SPY",
    lookback_days: int = 25,
) -> dict:
    """Count IBD-style distribution days on an index.

    A distribution day is a decline of at least 0.2% on volume higher
    than the prior session — a footprint of institutional selling.
    Five or more within ~25 sessions signals a market under pressure.

    Args:
        provider: Market data provider.
        index_symbol: Index proxy to analyze (SPY, QQQ).
        lookback_days: Trailing session window (default 25).

    Returns:
        Dict: {index_symbol, lookback_days, count, dates,
        signal: healthy | caution | under-pressure}.
    """
    df = await provider.get_ohlcv(index_symbol, period="6mo")
    change = df["Close"].pct_change()
    higher_volume = df["Volume"] > df["Volume"].shift(1)
    is_distribution = (change <= _DISTRIBUTION_DAY_LOSS) & higher_volume
    recent = is_distribution.iloc[-lookback_days:]
    dates = [idx.date().isoformat() for idx in recent[recent].index]
    return {
        "index_symbol": index_symbol,
        "lookback_days": lookback_days,
        "count": len(dates),
        "dates": dates,
        "signal": _distribution_signal(len(dates)),
    }


def _distribution_signal(count: int) -> str:
    if count >= 5:
        return "under-pressure"
    if count >= 3:
        return "caution"
    return "healthy"


async def detect_follow_through_day(
    provider: AbstractDataProvider,
    index_symbol: str = "SPY",
    lookback_days: int = 60,
) -> dict:
    """Detect an O'Neil Follow-Through Day after a correction low.

    From the lowest close in the window, a rally attempt begins; a
    Follow-Through Day occurs on rally day 4 or later when the index
    gains >= 1.25% on volume higher than the prior session, confirming
    a new uptrend.

    Args:
        provider: Market data provider.
        index_symbol: Index proxy to analyze (SPY, QQQ).
        lookback_days: Trailing session window to search (default 60).

    Returns:
        Dict: {index_symbol, correction_low_date, rally_day, ftd_detected,
        ftd_date, status: confirmed-uptrend | rally-attempt | correction}.
    """
    df = await provider.get_ohlcv(index_symbol, period="6mo")
    window = df.iloc[-lookback_days:]
    low_pos = int(window["Close"].to_numpy().argmin())
    after = window.iloc[low_pos:]
    ftd_date = _find_ftd(after)
    rally_day = len(after) - 1
    status = _ftd_status(after, ftd_date, rally_day)
    return {
        "index_symbol": index_symbol,
        "correction_low_date": after.index[0].date().isoformat(),
        "rally_day": rally_day,
        "ftd_detected": ftd_date is not None,
        "ftd_date": ftd_date,
        "status": status,
    }


def _find_ftd(after: pd.DataFrame) -> str | None:
    """Scan sessions after the low for the first qualifying FTD."""
    change = after["Close"].pct_change()
    higher_volume = after["Volume"] > after["Volume"].shift(1)
    for day_index in range(_FTD_MIN_RALLY_DAY, len(after)):
        if change.iloc[day_index] >= _FTD_MIN_GAIN and bool(higher_volume.iloc[day_index]):
            return str(after.index[day_index].date().isoformat())
    return None


def _ftd_status(after: pd.DataFrame, ftd_date: str | None, rally_day: int) -> str:
    if ftd_date is not None:
        return "confirmed-uptrend"
    if rally_day >= 1 and float(after["Close"].iloc[-1]) > float(after["Close"].iloc[0]):
        return "rally-attempt"
    return "correction"


async def compute_percent_above_ma(
    provider: AbstractDataProvider,
    universe: str = "sector_etfs",
    ma_periods: list[int] | None = None,
    allow_warmup: bool = True,
) -> dict:
    """Percentage of universe members trading above each moving average.

    ``sector_etfs`` computes directly from ETF data (fast path). Other
    universes read the BreadthStore; on a cold store the universe is
    warmed up when ``allow_warmup`` is True, otherwise the sector-ETF
    proxy is returned (flagged ``proxy: true``).

    Args:
        provider: Market data provider.
        universe: Universe name (sector_etfs, sp500, nasdaq100).
        ma_periods: Moving average periods (default [20, 50, 200]).
        allow_warmup: Permit a slow first-use cache warm-up.

    Returns:
        Dict: {universe, proxy, n_symbols, pct_above: {period: pct}}.
    """
    ma_periods = ma_periods or [20, 50, 200]
    closes, proxy = await _universe_or_proxy_closes(provider, universe, allow_warmup)
    pct_above = {p: _pct_above(closes, p) for p in ma_periods}
    return {
        "universe": universe,
        "proxy": proxy,
        "n_symbols": len(closes),
        "pct_above": pct_above,
    }


async def _universe_or_proxy_closes(
    provider: AbstractDataProvider, universe: str, allow_warmup: bool
) -> tuple[list[pd.Series], bool]:
    """Close series for the universe, or the sector-ETF proxy (proxy flag)."""
    if universe != "sector_etfs":
        matrix = await _load_universe_closes(provider, universe, allow_warmup)
        if matrix is not None:
            return [matrix[c].dropna() for c in matrix.columns], False
        logger.info("Breadth store cold for %s; using sector-ETF proxy", universe)
    frames = await provider.get_batch_ohlcv(list(SECTOR_ETFS.values()), period="2y")
    closes = [df["Close"] for df in frames.values() if not df.empty]
    return closes, universe != "sector_etfs"


async def _load_universe_closes(
    provider: AbstractDataProvider, universe: str, allow_warmup: bool
) -> pd.DataFrame | None:
    """Load the universe close matrix, or None when cold and warm-up disallowed."""
    store = BreadthStore()
    try:
        ready = await store.ensure(provider, universe, allow_warmup=allow_warmup)
    except Exception as exc:
        logger.warning("Breadth store unavailable for %s: %s", universe, exc)
        return None
    if not ready:
        return None
    matrix = await store.load_field(universe, "close")
    return matrix if not matrix.empty else None


async def compute_advance_decline(
    provider: AbstractDataProvider,
    universe: str = "sp500",
    period: str = "3m",
) -> pd.DataFrame:
    """Compute the advance/decline line for a universe (deep path).

    Warms the breadth store on first use (slow), incremental afterwards.

    Args:
        provider: Market data provider.
        universe: Universe name (sp500, nasdaq100, sector_etfs).
        period: History window returned — 1m, 3m, 6m, 1y.

    Returns:
        DataFrame indexed by date with columns: Advancing, Declining,
        Unchanged, NetAdvancing, ADLine, ADLine_SMA10, ADLine_SMA20.
    """
    matrix = await _load_universe_closes(provider, universe, allow_warmup=True)
    if matrix is None:
        return pd.DataFrame()
    diff = matrix.diff().iloc[1:]
    advancing = (diff > 0).sum(axis=1)
    declining = (diff < 0).sum(axis=1)
    net = advancing - declining
    ad_line = net.cumsum()
    result = pd.DataFrame(
        {
            "Advancing": advancing,
            "Declining": declining,
            "Unchanged": (diff == 0).sum(axis=1),
            "NetAdvancing": net,
            "ADLine": ad_line,
            "ADLine_SMA10": ad_line.rolling(10).mean(),
            "ADLine_SMA20": ad_line.rolling(20).mean(),
        }
    )
    return result.iloc[-_HISTORY_DAYS[period]:]


async def compute_new_highs_lows(
    provider: AbstractDataProvider,
    universe: str = "sp500",
    period: str = "3m",
) -> pd.DataFrame:
    """Count new 52-week highs and lows per day (deep path).

    Args:
        provider: Market data provider.
        universe: Universe name (sp500, nasdaq100, sector_etfs).
        period: History window returned — 1m, 3m, 6m, 1y.

    Returns:
        DataFrame indexed by date with columns: NewHighs, NewLows,
        NetNewHighs, HighLowRatio, HL_SMA10.
    """
    matrix = await _load_universe_closes(provider, universe, allow_warmup=True)
    if matrix is None:
        return pd.DataFrame()
    roll_max = matrix.rolling(252, min_periods=126).max()
    roll_min = matrix.rolling(252, min_periods=126).min()
    new_highs = ((matrix >= roll_max) & roll_max.notna()).sum(axis=1)
    new_lows = ((matrix <= roll_min) & roll_min.notna()).sum(axis=1)
    total = new_highs + new_lows
    ratio = (new_highs / total.where(total > 0)).round(4)
    result = pd.DataFrame(
        {
            "NewHighs": new_highs,
            "NewLows": new_lows,
            "NetNewHighs": new_highs - new_lows,
            "HighLowRatio": ratio,
            "HL_SMA10": ratio.rolling(10).mean().round(4),
        }
    )
    return result.iloc[-_HISTORY_DAYS[period]:]


async def compute_breadth_thrust(
    provider: AbstractDataProvider,
    universe: str = "sp500",
    period: str = "3m",
) -> dict:
    """Compute a McClellan-style breadth oscillator (deep path).

    Oscillator = EMA19 - EMA39 of the ratio-adjusted net advances
    ((advancing - declining) / total * 1000). Readings above +50 mark a
    bullish thrust, below -50 a bearish one.

    Args:
        provider: Market data provider.
        universe: Universe name (sp500, nasdaq100, sector_etfs).
        period: History window returned — 1m, 3m, 6m, 1y.

    Returns:
        Dict: {thrust_value, thrust_signal, history: DataFrame with
        NetRatio, EMA19, EMA39, Oscillator}.
    """
    matrix = await _load_universe_closes(provider, universe, allow_warmup=True)
    if matrix is None:
        return {"thrust_value": None, "thrust_signal": "unavailable", "history": pd.DataFrame()}
    diff = matrix.diff().iloc[1:]
    advancing = (diff > 0).sum(axis=1)
    declining = (diff < 0).sum(axis=1)
    total = advancing + declining
    net_ratio = ((advancing - declining) / total.where(total > 0)) * 1000
    ema19 = net_ratio.ewm(span=19).mean()
    ema39 = net_ratio.ewm(span=39).mean()
    oscillator = ema19 - ema39
    history = pd.DataFrame(
        {"NetRatio": net_ratio, "EMA19": ema19, "EMA39": ema39, "Oscillator": oscillator}
    ).round(2)
    value = round(float(oscillator.iloc[-1]), 2)
    return {
        "thrust_value": value,
        "thrust_signal": _thrust_signal(value),
        "history": history.iloc[-_HISTORY_DAYS[period]:],
    }


def _thrust_signal(value: float) -> str:
    if value > 50:
        return "bullish"
    if value < -50:
        return "bearish"
    return "neutral"


def _pct_above(closes: list[pd.Series], ma_period: int) -> float | None:
    """Share of series whose last close exceeds its own SMA, as a percentage."""
    eligible = [c for c in closes if len(c) >= ma_period]
    if not eligible:
        return None
    above = sum(
        1 for c in eligible if float(c.iloc[-1]) > float(c.iloc[-ma_period:].mean())
    )
    return round(above / len(eligible) * 100, 2)


async def detect_market_regime(
    provider: AbstractDataProvider,
    universe: str = "sp500",
) -> dict:
    """Composite market regime detection with exposure guidance.

    Combines cross-asset ratios (equal-weight vs cap-weight breadth,
    small-cap risk appetite, cyclical vs defensive, stocks vs bonds,
    credit), index trend, volatility, and sector-ETF breadth into a
    0-100 score mapped to a regime label and a recommended equity
    exposure band.

    Args:
        provider: Market data provider.
        universe: Universe for the breadth component. Uses the breadth
            store when already warm; otherwise falls back to the
            sector-ETF proxy (never blocks on a cold-cache warm-up).

    Returns:
        Dict: {regime, score, confidence, recommended_exposure:
        {min_pct, max_pct, label}, components}.
    """
    symbols = list(_CROSS_ASSET_TICKERS.values()) + list(SECTOR_ETFS.values())
    frames = await provider.get_batch_ohlcv(symbols, period="1y")
    vix = await _fetch_vix(provider)
    scores = _component_scores(frames, vix)
    breadth_source = "sector-etf-proxy"
    deep_breadth = await _deep_breadth_score(provider, universe)
    if deep_breadth is not None:
        scores["breadth"] = deep_breadth
        breadth_source = f"universe:{universe}"
    weighted = _weighted_score(scores)
    composite = round(50 * (1 + weighted), 2)
    regime, exposure = _regime_from_score(composite)
    components = _component_labels(scores, vix)
    components["breadth_source"] = breadth_source
    return {
        "regime": regime,
        "score": composite,
        "confidence": _confidence(scores, weighted),
        "recommended_exposure": exposure,
        "components": components,
        "as_of": datetime.now(UTC).date().isoformat(),
    }


async def _deep_breadth_score(
    provider: AbstractDataProvider, universe: str
) -> float | None:
    """Breadth score from the warm universe store, or None to use the proxy."""
    if universe == "sector_etfs":
        return None
    result = await compute_percent_above_ma(
        provider, universe=universe, allow_warmup=False
    )
    if result["proxy"]:
        return None
    pct = result["pct_above"].get(50)
    return round(pct / 50 - 1, 4) if pct is not None else None


async def _fetch_vix(provider: AbstractDataProvider) -> float | None:
    """Fetch the latest VIX close; None when the provider can't supply it."""
    try:
        df = await provider.get_ohlcv(_VIX_SYMBOL, period="3mo")
        return round(float(df["Close"].iloc[-1]), 2)
    except Exception as exc:
        logger.warning("VIX unavailable: %s", exc)
        return None


def _ratio_score(
    frames: dict[str, pd.DataFrame], num: str, den: str, scale: float
) -> float | None:
    """Score the 63-session change of a price ratio, clipped to [-1, 1]."""
    df_num, df_den = frames.get(num), frames.get(den)
    if df_num is None or df_den is None or df_num.empty or df_den.empty:
        return None
    ratio = (df_num["Close"] / df_den["Close"]).dropna()
    if len(ratio) <= 63:
        return None
    change = float(ratio.iloc[-1] / ratio.iloc[-64] - 1)
    return round(max(-1.0, min(1.0, change / scale)), 4)


def _trend_score(frames: dict[str, pd.DataFrame]) -> float | None:
    """Score SPY's position vs its 50 and 200 SMAs in [-1, 1]."""
    spy = frames.get("SPY")
    if spy is None or len(spy) < 200:
        return None
    close = spy["Close"]
    above50 = float(close.iloc[-1]) > float(close.iloc[-50:].mean())
    above200 = float(close.iloc[-1]) > float(close.iloc[-200:].mean())
    return (0.5 if above50 else -0.5) + (0.5 if above200 else -0.5)


def _vix_score(vix: float | None) -> float:
    """Score volatility regime in [-1, 1] (low VIX is supportive)."""
    if vix is None:
        return 0.0
    thresholds = [(15.0, 1.0), (20.0, 0.5), (25.0, 0.0), (30.0, -0.5)]
    for level, score in thresholds:
        if vix < level:
            return score
    return -1.0


def _breadth_scores(frames: dict[str, pd.DataFrame]) -> tuple[float | None, float | None]:
    """(pct of sector ETFs above 50 SMA, pct with positive 1m return), as [-1, 1]."""
    closes = [
        frames[etf]["Close"]
        for etf in SECTOR_ETFS.values()
        if etf in frames and not frames[etf].empty
    ]
    if not closes:
        return None, None
    above = _pct_above(closes, 50)
    eligible = [c for c in closes if len(c) > 21]
    positive = (
        sum(1 for c in eligible if float(c.iloc[-1]) > float(c.iloc[-22])) / len(eligible)
        if eligible
        else None
    )
    breadth = round(above / 50 - 1, 4) if above is not None else None
    participation = round(positive * 2 - 1, 4) if positive is not None else None
    return breadth, participation


_COMPONENT_WEIGHTS: dict[str, float] = {
    "concentration": 0.10,
    "size": 0.10,
    "cyclical_defensive": 0.10,
    "stock_bond": 0.10,
    "credit": 0.10,
    "trend": 0.20,
    "volatility": 0.10,
    "breadth": 0.10,
    "participation": 0.10,
}


def _component_scores(
    frames: dict[str, pd.DataFrame], vix: float | None
) -> dict[str, float | None]:
    """Compute all regime component scores in [-1, 1] (None = unavailable)."""
    breadth, participation = _breadth_scores(frames)
    return {
        "concentration": _ratio_score(frames, "RSP", "SPY", 0.05),
        "size": _ratio_score(frames, "IWM", "SPY", 0.05),
        "cyclical_defensive": _ratio_score(frames, "XLY", "XLP", 0.05),
        "stock_bond": _ratio_score(frames, "SPY", "TLT", 0.10),
        "credit": _ratio_score(frames, "HYG", "LQD", 0.03),
        "trend": _trend_score(frames),
        "volatility": _vix_score(vix),
        "breadth": breadth,
        "participation": participation,
    }


def _weighted_score(scores: dict[str, float | None]) -> float:
    """Weighted mean of available component scores, in [-1, 1]."""
    total_weight = sum(
        _COMPONENT_WEIGHTS[name] for name, s in scores.items() if s is not None
    )
    if total_weight == 0:
        return 0.0
    weighted = sum(
        _COMPONENT_WEIGHTS[name] * s for name, s in scores.items() if s is not None
    )
    return weighted / total_weight


def _confidence(scores: dict[str, float | None], weighted: float) -> float:
    """Fraction of available components agreeing with the composite direction."""
    available = [s for s in scores.values() if s is not None]
    if not available or weighted == 0:
        return 0.5
    agreeing = sum(1 for s in available if s * weighted > 0)
    return round(agreeing / len(available), 4)


def _regime_from_score(composite: float) -> tuple[str, dict]:
    """Map a 0-100 composite score to (regime label, exposure band)."""
    for threshold, regime, exposure in _REGIME_BANDS:
        if composite >= threshold:
            return regime, exposure
    return "strong-bear", _REGIME_BANDS[-1][2]


_SENTIMENT_LABELS: list[tuple[float, str]] = [
    (60.0, "extreme-greed"),
    (20.0, "greed"),
    (-20.0, "neutral"),
    (-60.0, "fear"),
]


async def compute_market_sentiment(provider: AbstractDataProvider) -> dict:
    """Composite market sentiment from volatility, breadth, and momentum.

    Fast path only. Score ranges -100 (extreme fear) to +100 (extreme
    greed). Put/call data is not available from current providers and is
    reported as null.

    Args:
        provider: Market data provider.

    Returns:
        Dict: {score, label, components: {put_call_ratio, vix_level,
        vix_term_structure, breadth_score, momentum_score}}.
    """
    vix = await _fetch_vix(provider)
    vix3m = await _fetch_latest_close(provider, "^VIX3M")
    momentum = await _momentum_score(provider)
    breadth_result = await compute_percent_above_ma(provider, universe="sector_etfs")
    pct50 = breadth_result["pct_above"].get(50)
    breadth = round(pct50 * 2 - 100, 2) if pct50 is not None else None
    term_structure = _vix_term_structure(vix, vix3m)
    parts = [
        _vix_score(vix) * 100 if vix is not None else None,
        _term_structure_score(term_structure),
        breadth,
        momentum,
    ]
    available = [p for p in parts if p is not None]
    score = round(sum(available) / len(available), 2) if available else 0.0
    return {
        "score": score,
        "label": _sentiment_label(score),
        "components": {
            "put_call_ratio": None,
            "vix_level": vix,
            "vix_term_structure": term_structure,
            "breadth_score": breadth,
            "momentum_score": momentum,
        },
    }


async def _fetch_latest_close(provider: AbstractDataProvider, symbol: str) -> float | None:
    try:
        df = await provider.get_ohlcv(symbol, period="3mo")
        return round(float(df["Close"].iloc[-1]), 2)
    except Exception as exc:
        logger.warning("%s unavailable: %s", symbol, exc)
        return None


async def _momentum_score(provider: AbstractDataProvider) -> float | None:
    """SPY 1m+3m momentum scaled to [-100, 100]."""
    try:
        df = await provider.get_ohlcv("SPY", period="1y")
    except Exception as exc:
        logger.warning("SPY momentum unavailable: %s", exc)
        return None
    close = df["Close"]
    if len(close) <= 63:
        return None
    ret_1m = float(close.iloc[-1] / close.iloc[-22] - 1)
    ret_3m = float(close.iloc[-1] / close.iloc[-64] - 1)
    raw = (ret_1m / 0.03 + ret_3m / 0.06) / 2
    return round(max(-1.0, min(1.0, raw)) * 100, 2)


def _vix_term_structure(vix: float | None, vix3m: float | None) -> str | None:
    if vix is None or vix3m is None:
        return None
    return "contango" if vix < vix3m else "backwardation"


def _term_structure_score(term_structure: str | None) -> float | None:
    if term_structure is None:
        return None
    return 25.0 if term_structure == "contango" else -50.0


def _sentiment_label(score: float) -> str:
    for threshold, label in _SENTIMENT_LABELS:
        if score >= threshold:
            return label
    return "extreme-fear"


def _direction(score: float | None, positive: str, negative: str) -> str:
    if score is None:
        return "unavailable"
    if score > 0.1:
        return positive
    if score < -0.1:
        return negative
    return "neutral"


def _component_labels(scores: dict[str, float | None], vix: float | None) -> dict:
    """Human-readable component summary for reports and the agent."""
    return {
        "cross_asset": {
            "concentration": _direction(scores["concentration"], "broadening", "narrowing"),
            "size": _direction(scores["size"], "risk-on", "risk-off"),
            "cyclical_defensive": _direction(
                scores["cyclical_defensive"], "cyclicals-leading", "defensives-leading"
            ),
            "stock_bond": _direction(scores["stock_bond"], "stocks-leading", "bonds-leading"),
            "credit": _direction(scores["credit"], "risk-appetite", "credit-stress"),
        },
        "trend_direction": _direction(scores["trend"], "uptrend", "downtrend"),
        "volatility_regime": f"vix={vix}" if vix is not None else "unavailable",
        "breadth_health": _direction(scores["breadth"], "healthy", "weak"),
        "sector_participation": _direction(scores["participation"], "broad", "narrow"),
        "scores": dict(scores),
    }

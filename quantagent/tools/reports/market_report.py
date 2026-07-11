"""Daily market brief report generator."""
from __future__ import annotations

import logging
from datetime import UTC, datetime

import pandas as pd

from quantagent.tools.breadth_store import BreadthStore
from quantagent.tools.market_overview import get_market_summary, get_top_movers
from quantagent.tools.providers.base import AbstractDataProvider
from quantagent.tools.reports._shared import dict_lines, safe_section
from quantagent.tools.reports.base import Report, ReportConfig, ReportSection
from quantagent.tools.sector_analysis import (
    detect_sector_rotation,
    get_sector_performance_ranked,
)

logger = logging.getLogger(__name__)


async def generate_market_daily(
    provider: AbstractDataProvider,
    config: ReportConfig | None = None,
) -> Report:
    """Generate the daily market brief.

    Sections: market overview (indices, key levels), regime & exposure,
    timing signals, breadth, sentiment, ranked sector performance,
    sector rotation, and top movers (only when the breadth cache is
    warm — the brief itself stays fast-path).

    Args:
        provider: Market data provider.
        config: Optional report options.
    """
    config = config or ReportConfig()
    summary = await get_market_summary(provider)
    sections = [
        _overview_section(summary),
        _regime_section(summary),
        _timing_section(summary),
        _breadth_section(summary),
        ReportSection(
            title="Sentiment",
            content=dict_lines(summary.get("sentiment", {})),
        ),
        await safe_section("Sector Performance", _sector_section(provider)),
        await safe_section("Sector Rotation", _rotation_section(provider)),
        await safe_section("Top Movers", _movers_section(provider)),
    ]
    title = config.title or f"Market Daily Brief — {datetime.now(UTC).date().isoformat()}"
    return Report(title=title, sections=sections, metadata={"type": "market_daily"})


def _overview_section(summary: dict) -> ReportSection:
    indices = summary.get("indices", {})
    rows = [{"symbol": sym, **data} for sym, data in indices.items()]
    levels = summary.get("key_levels", {})
    content = dict_lines(
        {"support": levels.get("support"), "resistance": levels.get("resistance")}
    )
    return ReportSection(
        title="Market Overview", content=content, tables=[pd.DataFrame(rows)]
    )


def _regime_section(summary: dict) -> ReportSection:
    regime = summary.get("regime", {})
    exposure = summary.get("recommended_exposure", {})
    content = dict_lines(
        {
            "regime": regime.get("regime"),
            "score": regime.get("score"),
            "confidence": regime.get("confidence"),
            "recommended_exposure": (
                f"{exposure.get('min_pct')}–{exposure.get('max_pct')}% "
                f"({exposure.get('label')})"
            ),
            "trend": regime.get("components", {}).get("trend_direction"),
            "volatility": regime.get("components", {}).get("volatility_regime"),
        }
    )
    return ReportSection(title="Market Regime & Exposure", content=content)


def _timing_section(summary: dict) -> ReportSection:
    timing = summary.get("timing", {})
    dist = timing.get("distribution_days", {})
    ftd = timing.get("follow_through", {})
    content = dict_lines(
        {
            "distribution_days": f"{dist.get('count')} in {dist.get('lookback_days')} "
            f"sessions ({dist.get('signal')})",
            "follow_through_status": ftd.get("status"),
            "ftd_date": ftd.get("ftd_date"),
            "correction_low": ftd.get("correction_low_date"),
        }
    )
    return ReportSection(title="Timing Signals", content=content)


def _breadth_section(summary: dict) -> ReportSection:
    breadth = summary.get("breadth", {})
    pct = breadth.get("pct_above", {})
    content = dict_lines(
        {
            "universe": breadth.get("universe"),
            "proxy": breadth.get("proxy"),
            **{f"pct_above_{p}dma": v for p, v in pct.items()},
        }
    )
    return ReportSection(title="Breadth", content=content)


async def _sector_section(provider: AbstractDataProvider) -> ReportSection:
    df = await get_sector_performance_ranked(provider)
    return ReportSection(title="Sector Performance", tables=[df])


async def _rotation_section(provider: AbstractDataProvider) -> ReportSection:
    rotation = await detect_sector_rotation(provider)
    return ReportSection(title="Sector Rotation", content=dict_lines(rotation))


async def _movers_section(provider: AbstractDataProvider) -> ReportSection:
    if not await BreadthStore().is_warm("sp500"):
        return ReportSection(
            title="Top Movers",
            content="_Breadth cache cold — run warm_breadth_cache to enable._",
        )
    gainers = await get_top_movers(provider, direction="up", count=5)
    losers = await get_top_movers(provider, direction="down", count=5)
    return ReportSection(
        title="Top Movers", content="Gainers, then losers:", tables=[gainers, losers]
    )

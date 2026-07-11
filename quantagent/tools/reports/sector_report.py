"""Sector deep-dive report generator."""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from quantagent.tools.providers.base import AbstractDataProvider
from quantagent.tools.reports._shared import dict_lines, safe_section
from quantagent.tools.reports.base import Report, ReportConfig, ReportSection
from quantagent.tools.sector_analysis import (
    compute_sector_relative_strength,
    detect_sector_rotation,
    get_industry_performance,
    get_sector_performance_ranked,
)
from quantagent.tools.technical import summarize_technicals
from quantagent.tools.universe import SECTOR_ETFS

logger = logging.getLogger(__name__)


async def generate_sector_report(
    provider: AbstractDataProvider,
    sector: str,
    config: ReportConfig | None = None,
) -> Report:
    """Generate a sector analysis report.

    Sections: performance across timeframes, relative strength vs the
    benchmark, rotation context, sector ETF technicals, and industry
    breakdown (slow on a cold classification cache).

    Args:
        provider: Market data provider.
        sector: Sector name (must be one of the 11 GICS sectors).
        config: Optional report options.

    Raises:
        ValueError: For unknown sector names.
    """
    matched = _match_sector(sector)
    config = config or ReportConfig()
    sections = [
        await safe_section("Performance", _performance_section(provider, matched)),
        await safe_section(
            "Relative Strength", _rs_section(provider, matched, config.benchmark)
        ),
        await safe_section("Rotation Context", _rotation_section(provider, matched)),
        await safe_section("Technical Summary", _technical_section(provider, matched)),
        await safe_section("Industry Breakdown", _industry_section(provider, matched)),
    ]
    title = (
        config.title
        or f"{matched} Sector Report — {datetime.now(UTC).date().isoformat()}"
    )
    return Report(
        title=title, sections=sections, metadata={"type": "sector", "sector": matched}
    )


def _match_sector(sector: str) -> str:
    for name in SECTOR_ETFS:
        if name.lower() == sector.lower():
            return name
    raise ValueError(
        f"Unknown sector: {sector}. Valid sectors: {', '.join(SECTOR_ETFS)}"
    )


async def _performance_section(
    provider: AbstractDataProvider, sector: str
) -> ReportSection:
    df = await get_sector_performance_ranked(provider)
    row = df[df["sector"] == sector]
    rank = int(row.iloc[0]["rank"]) if not row.empty else None
    content = f"**Rank:** {rank} of {len(df)}" if rank else ""
    return ReportSection(title="Performance", content=content, tables=[df])


async def _rs_section(
    provider: AbstractDataProvider, sector: str, benchmark: str
) -> ReportSection:
    df = await compute_sector_relative_strength(provider, benchmark=benchmark)
    row = df[df["sector"] == sector]
    content = ""
    if not row.empty:
        r = row.iloc[0]
        content = dict_lines(
            {"rs_ratio": r["rs_ratio"], "rs_rank": int(r["rs_rank"]), "trend": r["trend"]}
        )
    return ReportSection(title="Relative Strength", content=content, tables=[df])


async def _rotation_section(
    provider: AbstractDataProvider, sector: str
) -> ReportSection:
    rotation = await detect_sector_rotation(provider)
    role = "neutral"
    for key in ("leading_sectors", "lagging_sectors", "improving_sectors",
                "deteriorating_sectors"):
        if sector in rotation.get(key, []):
            role = key.replace("_sectors", "")
            break
    content = f"**This sector is currently: {role}.**\n\n" + dict_lines(rotation)
    return ReportSection(title="Rotation Context", content=content)


async def _technical_section(
    provider: AbstractDataProvider, sector: str
) -> ReportSection:
    etf = SECTOR_ETFS[sector]
    df = await provider.get_ohlcv(etf, period="1y")
    summary = summarize_technicals(df)
    return ReportSection(
        title="Technical Summary",
        content=f"Sector ETF: **{etf}**\n\n" + dict_lines(summary),
    )


async def _industry_section(
    provider: AbstractDataProvider, sector: str
) -> ReportSection:
    df = await get_industry_performance(provider, sector)
    if df.empty:
        return ReportSection(
            title="Industry Breakdown",
            content="_No industry classification data available._",
        )
    return ReportSection(title="Industry Breakdown", tables=[df])

"""Screening results report generator."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from quantagent.tools.providers.base import AbstractDataProvider
from quantagent.tools.reports.base import Report, ReportConfig, ReportSection
from quantagent.tools.screener import (
    screen_breakout_candidates,
    screen_by_technicals,
    screen_oversold_reversal,
    screen_stocks,
    screen_vcp_pattern,
)

logger = logging.getLogger(__name__)

_SCREEN_DESCRIPTIONS = {
    "fundamental": "Fundamental criteria screen",
    "technical": "Technical criteria screen",
    "vcp": "Volatility Contraction Pattern (Minervini)",
    "breakout": "52-week-high breakout candidates",
    "oversold": "Oversold reversal candidates",
}


async def _run_screen(
    provider: AbstractDataProvider,
    screen_type: str,
    criteria: dict[str, Any] | None,
    universe: str,
) -> Any:
    if screen_type == "fundamental":
        return await screen_stocks(provider, universe=universe, criteria=criteria, limit=50)
    if screen_type == "technical":
        return await screen_by_technicals(provider, criteria or {}, universe=universe)
    if screen_type == "vcp":
        return await screen_vcp_pattern(provider, universe=universe)
    if screen_type == "breakout":
        return await screen_breakout_candidates(provider, universe=universe)
    if screen_type == "oversold":
        return await screen_oversold_reversal(provider, universe=universe)
    raise ValueError(
        f"Unknown screen type: {screen_type}. "
        f"Valid types: {', '.join(_SCREEN_DESCRIPTIONS)}"
    )


async def generate_screening_report(
    provider: AbstractDataProvider,
    screen_type: str = "fundamental",
    criteria: dict[str, Any] | None = None,
    universe: str = "sp500",
    config: ReportConfig | None = None,
) -> Report:
    """Run a screen and package the results as a report.

    Args:
        provider: Market data provider.
        screen_type: fundamental | technical | vcp | breakout | oversold.
        criteria: Criteria for fundamental/technical screens.
        universe: Universe to screen.
        config: Optional report options.
    """
    config = config or ReportConfig()
    results = await _run_screen(provider, screen_type, criteria, universe)
    parameters = ReportSection(
        title="Parameters",
        content=(
            f"- **Screen:** {_SCREEN_DESCRIPTIONS[screen_type]}\n"
            f"- **Universe:** {universe}\n"
            f"- **Criteria:** {criteria or 'defaults'}\n"
            f"- **Matches:** {len(results)}"
        ),
    )
    results_section = (
        ReportSection(title="Results", tables=[results])
        if not results.empty
        else ReportSection(title="Results", content="_No stocks matched._")
    )
    notes = ReportSection(
        title="Notes",
        content=(
            "_Screen results are idea candidates, not recommendations. "
            "Validate with a deep-dive analysis and check the market regime "
            "before acting._"
        ),
    )
    title = (
        config.title
        or f"Screening Report ({screen_type}) — {datetime.now(UTC).date().isoformat()}"
    )
    return Report(
        title=title,
        sections=[parameters, results_section, notes],
        metadata={"type": "screening", "screen_type": screen_type, "universe": universe},
    )

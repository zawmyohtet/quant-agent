"""Portfolio review report generator."""
from __future__ import annotations

import logging
from datetime import UTC, datetime

import pandas as pd

from quantagent.tools.portfolio import (
    compute_portfolio_metrics,
    monte_carlo_simulation,
    optimize_portfolio,
)
from quantagent.tools.providers.base import AbstractDataProvider
from quantagent.tools.reports._shared import dict_lines, safe_section
from quantagent.tools.reports.base import Report, ReportConfig, ReportSection
from quantagent.tools.sector_analysis import classify_symbols

logger = logging.getLogger(__name__)


def _normalize_weights(
    symbols: list[str], weights: dict[str, float] | None
) -> dict[str, float]:
    if not weights:
        return {sym: round(1 / len(symbols), 4) for sym in symbols}
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("Portfolio weights must sum to a positive value")
    return {sym: round(w / total, 4) for sym, w in weights.items()}


async def generate_portfolio_report(
    provider: AbstractDataProvider,
    symbols: list[str],
    weights: dict[str, float] | None = None,
    config: ReportConfig | None = None,
) -> Report:
    """Generate a portfolio review report.

    Sections: allocation, risk metrics vs benchmark, sector exposure,
    optimization suggestion (max Sharpe), and Monte Carlo simulation.

    Args:
        provider: Market data provider.
        symbols: Portfolio symbols.
        weights: Optional weights (normalized; equal weight when omitted).
        config: Optional report options.
    """
    symbols = [s.upper() for s in symbols]
    weight_map = _normalize_weights(symbols, weights)
    config = config or ReportConfig()
    sections = [
        _allocation_section(weight_map),
        await safe_section(
            "Risk Metrics", _risk_section(provider, weight_map, config.benchmark)
        ),
        await safe_section("Sector Exposure", _exposure_section(provider, weight_map)),
        await safe_section("Optimization Suggestion", _optimization_section(provider, symbols)),
        await safe_section("Monte Carlo", _monte_carlo_section(provider, weight_map)),
    ]
    title = config.title or f"Portfolio Review — {datetime.now(UTC).date().isoformat()}"
    return Report(
        title=title,
        sections=sections,
        metadata={"type": "portfolio", "symbols": symbols},
    )


def _allocation_section(weight_map: dict[str, float]) -> ReportSection:
    df = pd.DataFrame(
        [{"symbol": sym, "weight": w} for sym, w in weight_map.items()]
    ).sort_values("weight", ascending=False)
    return ReportSection(title="Allocation", tables=[df.reset_index(drop=True)])


async def _risk_section(
    provider: AbstractDataProvider, weight_map: dict[str, float], benchmark: str
) -> ReportSection:
    metrics = await compute_portfolio_metrics(provider, weight_map, benchmark=benchmark)
    return ReportSection(title="Risk Metrics", content=dict_lines(metrics))


async def _exposure_section(
    provider: AbstractDataProvider, weight_map: dict[str, float]
) -> ReportSection:
    classifications = await classify_symbols(provider, list(weight_map))
    by_sector: dict[str, float] = {}
    for sym, weight in weight_map.items():
        sector = classifications.get(sym, {}).get("sector") or "Unknown"
        by_sector[sector] = round(by_sector.get(sector, 0.0) + weight, 4)
    df = pd.DataFrame(
        [{"sector": s, "weight": w} for s, w in by_sector.items()]
    ).sort_values("weight", ascending=False)
    return ReportSection(title="Sector Exposure", tables=[df.reset_index(drop=True)])


async def _optimization_section(
    provider: AbstractDataProvider, symbols: list[str]
) -> ReportSection:
    result = await optimize_portfolio(provider, symbols, method="max_sharpe")
    content = (
        "Max-Sharpe weights (suggestion, not advice):\n\n" + dict_lines(result)
    )
    return ReportSection(title="Optimization Suggestion", content=content)


async def _monte_carlo_section(
    provider: AbstractDataProvider, weight_map: dict[str, float]
) -> ReportSection:
    result = await monte_carlo_simulation(provider, weight_map)
    return ReportSection(title="Monte Carlo", content=dict_lines(result))

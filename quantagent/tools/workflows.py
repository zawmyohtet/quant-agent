"""Workflow engine: ordered tool steps with output passing.

Built-in workflows cover the recurring routines (daily market check,
weekly sector review, stock research, screening pipeline, portfolio
review). Users can define their own as YAML files under
``~/.quantagent/workflows/<name>.yaml``:

.. code-block:: yaml

    name: my_morning_routine
    description: "My personal morning market review"
    steps:
      - tool: get_market_summary
        parameters: {}
        output_key: market
      - tool: screen_oversold_reversal
        parameters: {rsi_threshold: 35}
        output_key: candidates

String parameters of the form ``$key`` (or ``$key.field``) are resolved
from earlier steps' outputs.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field

from quantagent.tools._paths import workflows_dir
from quantagent.tools.conviction import synthesize_conviction
from quantagent.tools.event_analysis import analyze_earnings_impact
from quantagent.tools.market_breadth import (
    compute_advance_decline,
    compute_market_sentiment,
    compute_new_highs_lows,
    compute_percent_above_ma,
    count_distribution_days,
    detect_follow_through_day,
    detect_market_regime,
)
from quantagent.tools.market_data import get_fundamentals, get_news, get_quote
from quantagent.tools.market_overview import (
    get_market_summary,
    get_most_active,
    get_top_movers,
)
from quantagent.tools.pair_trading import compute_spread_metrics, find_cointegrated_pairs
from quantagent.tools.portfolio import compute_portfolio_metrics, optimize_portfolio
from quantagent.tools.providers.base import AbstractDataProvider
from quantagent.tools.screener import (
    screen_breakout_candidates,
    screen_by_technicals,
    screen_oversold_reversal,
    screen_stocks,
    screen_vcp_pattern,
)
from quantagent.tools.sector_analysis import (
    compute_sector_relative_strength,
    detect_sector_rotation,
    get_sector_performance_ranked,
)

logger = logging.getLogger(__name__)


class WorkflowStep(BaseModel):
    """One workflow step: a registered tool plus parameters."""

    model_config = ConfigDict(frozen=True)
    tool_name: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    output_key: str


class Workflow(BaseModel):
    """An ordered sequence of tool steps."""

    model_config = ConfigDict(frozen=True)
    name: str
    description: str = ""
    steps: list[WorkflowStep]
    estimated_duration: str = ""


class WorkflowResult(BaseModel):
    """Outcome of a workflow run."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
    workflow_name: str
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    step_results: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""


StepFn = Callable[..., Awaitable[Any]]

# Tools invokable as workflow steps. Every function takes the provider
# first; parameters come from the step definition.
STEP_REGISTRY: dict[str, StepFn] = {
    "get_market_summary": get_market_summary,
    "detect_market_regime": detect_market_regime,
    "count_distribution_days": count_distribution_days,
    "detect_follow_through_day": detect_follow_through_day,
    "compute_percent_above_ma": compute_percent_above_ma,
    "compute_advance_decline": compute_advance_decline,
    "compute_new_highs_lows": compute_new_highs_lows,
    "compute_market_sentiment": compute_market_sentiment,
    "get_sector_performance_ranked": get_sector_performance_ranked,
    "compute_sector_relative_strength": compute_sector_relative_strength,
    "detect_sector_rotation": detect_sector_rotation,
    "get_top_movers": get_top_movers,
    "get_most_active": get_most_active,
    "screen_stocks": screen_stocks,
    "screen_by_technicals": screen_by_technicals,
    "screen_vcp_pattern": screen_vcp_pattern,
    "screen_breakout_candidates": screen_breakout_candidates,
    "screen_oversold_reversal": screen_oversold_reversal,
    "get_quote": get_quote,
    "get_fundamentals": get_fundamentals,
    "get_news": get_news,
    "optimize_portfolio": optimize_portfolio,
    "compute_portfolio_metrics": compute_portfolio_metrics,
    "synthesize_conviction": synthesize_conviction,
    "find_cointegrated_pairs": find_cointegrated_pairs,
    "compute_spread_metrics": compute_spread_metrics,
    "analyze_earnings_impact": analyze_earnings_impact,
}


def _resolve_value(value: Any, results: dict[str, Any]) -> Any:
    """Resolve ``$key`` / ``$key.field`` references against prior outputs."""
    if not isinstance(value, str) or not value.startswith("$"):
        return value
    key, _, field = value[1:].partition(".")
    if key not in results:
        raise ValueError(f"Workflow reference '{value}' has no prior output '{key}'")
    resolved = results[key]
    if field:
        if not isinstance(resolved, dict) or field not in resolved:
            raise ValueError(f"Workflow reference '{value}' not found in output")
        return resolved[field]
    return resolved


def _resolve_parameters(
    parameters: dict[str, Any], results: dict[str, Any]
) -> dict[str, Any]:
    return {k: _resolve_value(v, results) for k, v in parameters.items()}


def _describe(value: Any) -> str:
    if isinstance(value, pd.DataFrame):
        return f"DataFrame ({len(value)} rows)"
    if isinstance(value, dict):
        keys = ", ".join(list(value)[:6])
        return f"dict ({keys})"
    if isinstance(value, list):
        return f"list ({len(value)} items)"
    return type(value).__name__


async def run_workflow(
    provider: AbstractDataProvider, workflow: Workflow
) -> WorkflowResult:
    """Execute a workflow's steps in order, passing outputs downstream.

    Raises:
        ValueError: On unknown step tools or unresolvable references.
    """
    results: dict[str, Any] = {}
    lines = []
    for step in workflow.steps:
        fn = STEP_REGISTRY.get(step.tool_name)
        if fn is None:
            raise ValueError(
                f"Unknown workflow tool: {step.tool_name}. "
                f"Available: {', '.join(sorted(STEP_REGISTRY))}"
            )
        params = _resolve_parameters(step.parameters, results)
        logger.info("Workflow %s: running %s", workflow.name, step.tool_name)
        output = await fn(provider, **params)
        results[step.output_key] = output
        lines.append(f"- {step.output_key} ({step.tool_name}): {_describe(output)}")
    return WorkflowResult(
        workflow_name=workflow.name,
        step_results=results,
        summary="\n".join(lines),
    )


# ── Built-in workflows ───────────────────────────────────────────────────────


def daily_market_check() -> Workflow:
    """Daily market review capped by the conviction synthesis."""
    return Workflow(
        name="daily_market_check",
        description="Market summary, regime, timing, sectors, and a final "
        "conviction score with exposure guidance.",
        estimated_duration="1-2 minutes",
        steps=[
            WorkflowStep(tool_name="get_market_summary", output_key="market"),
            WorkflowStep(
                tool_name="get_sector_performance_ranked", output_key="sectors"
            ),
            WorkflowStep(tool_name="detect_sector_rotation", output_key="rotation"),
            WorkflowStep(tool_name="synthesize_conviction", output_key="conviction"),
        ],
    )


def weekly_sector_review() -> Workflow:
    """Weekly sector rotation analysis."""
    return Workflow(
        name="weekly_sector_review",
        description="Sector ranking, relative strength, and rotation detection.",
        estimated_duration="1-2 minutes",
        steps=[
            WorkflowStep(
                tool_name="get_sector_performance_ranked", output_key="ranking"
            ),
            WorkflowStep(
                tool_name="compute_sector_relative_strength", output_key="rs"
            ),
            WorkflowStep(tool_name="detect_sector_rotation", output_key="rotation"),
        ],
    )


def stock_research(symbol: str) -> Workflow:
    """Deep-dive research on one symbol."""
    return Workflow(
        name="stock_research",
        description=f"Quote, fundamentals, and news for {symbol}.",
        estimated_duration="under 1 minute",
        steps=[
            WorkflowStep(
                tool_name="get_quote", parameters={"symbol": symbol}, output_key="quote"
            ),
            WorkflowStep(
                tool_name="get_fundamentals",
                parameters={"symbol": symbol},
                output_key="fundamentals",
            ),
            WorkflowStep(
                tool_name="get_news", parameters={"symbol": symbol}, output_key="news"
            ),
        ],
    )


def screening_pipeline(criteria: dict[str, Any] | None = None) -> Workflow:
    """Regime check, then a fundamental screen."""
    return Workflow(
        name="screening_pipeline",
        description="Market regime context followed by a fundamental screen.",
        estimated_duration="2-4 minutes",
        steps=[
            WorkflowStep(tool_name="detect_market_regime", output_key="regime"),
            WorkflowStep(
                tool_name="screen_stocks",
                parameters={"criteria": criteria or {}},
                output_key="candidates",
            ),
        ],
    )


def portfolio_rebalance_review(symbols: list[str]) -> Workflow:
    """Portfolio health check: risk metrics plus optimization."""
    weights = {sym.upper(): round(1 / len(symbols), 4) for sym in symbols}
    return Workflow(
        name="portfolio_rebalance_review",
        description=f"Risk metrics and max-Sharpe optimization for {', '.join(weights)}.",
        estimated_duration="1-2 minutes",
        steps=[
            WorkflowStep(
                tool_name="compute_portfolio_metrics",
                parameters={"weights": weights},
                output_key="risk",
            ),
            WorkflowStep(
                tool_name="optimize_portfolio",
                parameters={"symbols": [s.upper() for s in symbols]},
                output_key="optimization",
            ),
        ],
    )


BUILTIN_WORKFLOWS: dict[str, Callable[..., Workflow]] = {
    "daily_market_check": daily_market_check,
    "weekly_sector_review": weekly_sector_review,
    "stock_research": stock_research,
    "screening_pipeline": screening_pipeline,
    "portfolio_rebalance_review": portfolio_rebalance_review,
}

# Builtins whose factory requires the target argument.
_TARGET_REQUIRED = {"stock_research", "portfolio_rebalance_review"}


def load_custom_workflow(name: str) -> Workflow:
    """Load and validate a custom workflow YAML by name.

    Raises:
        ValueError: When the file is missing or malformed.
    """
    path = workflows_dir() / f"{name}.yaml"
    if not path.exists():
        raise ValueError(f"Unknown workflow: {name}")
    payload = yaml.safe_load(path.read_text())
    steps = [
        WorkflowStep(
            tool_name=step["tool"],
            parameters=step.get("parameters", {}) or {},
            output_key=step["output_key"],
        )
        for step in payload.get("steps", [])
    ]
    if not steps:
        raise ValueError(f"Workflow '{name}' defines no steps")
    return Workflow(
        name=payload.get("name", name),
        description=payload.get("description", ""),
        steps=steps,
        estimated_duration=payload.get("estimated_duration", ""),
    )


def list_workflows() -> list[dict]:
    """List built-in and custom workflows with descriptions."""
    builtin = [
        {"name": name, "type": "builtin", "description": factory.__doc__ or ""}
        for name, factory in BUILTIN_WORKFLOWS.items()
    ]
    custom = [
        {"name": p.stem, "type": "custom", "description": str(p)}
        for p in sorted(workflows_dir().glob("*.yaml"))
    ]
    return builtin + custom


def get_workflow(name: str, target: str = "") -> Workflow:
    """Resolve a workflow by name — built-in (with optional target) or custom.

    Args:
        name: Workflow name.
        target: Builtin argument — symbol for stock_research,
            comma-separated symbols for portfolio_rebalance_review.

    Raises:
        ValueError: For unknown names or missing required targets.
    """
    factory = BUILTIN_WORKFLOWS.get(name)
    if factory is None:
        return load_custom_workflow(name)
    if name in _TARGET_REQUIRED and not target:
        raise ValueError(f"Workflow '{name}' requires a target argument")
    if name == "stock_research":
        return factory(target.upper())
    if name == "portfolio_rebalance_review":
        return factory([s.strip() for s in target.split(",")])
    return factory()

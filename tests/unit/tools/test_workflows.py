"""Tests for the workflow engine."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from _synthetic import SyntheticProvider, make_ohlcv, trend_close

from quantagent.tools._paths import ensure_dir, workflows_dir
from quantagent.tools.universe import SECTOR_ETFS
from quantagent.tools.workflows import (
    BUILTIN_WORKFLOWS,
    Workflow,
    WorkflowStep,
    _resolve_parameters,
    get_workflow,
    list_workflows,
    load_custom_workflow,
    run_workflow,
)


def _market_provider() -> SyntheticProvider:
    frames: dict[str, pd.DataFrame] = {}
    for i, sym in enumerate(
        ["SPY", "QQQ", "DIA", "IWM", "RSP", "XLY", "XLP", "TLT", "HYG", "LQD", "AAPL"]
    ):
        frames[sym] = make_ohlcv(trend_close(n=300, drift=0.001, seed=i))
    for i, etf in enumerate(SECTOR_ETFS.values()):
        frames.setdefault(etf, make_ohlcv(trend_close(n=300, drift=0.001, seed=50 + i)))
    frames["^VIX"] = make_ohlcv(np.full(120, 14.0))
    frames["^VIX3M"] = make_ohlcv(np.full(120, 17.0))
    return SyntheticProvider(frames)


# ── Parameter resolution ─────────────────────────────────────────────────────


def test_resolve_parameters_pass_through() -> None:
    assert _resolve_parameters({"a": 1, "b": "x"}, {}) == {"a": 1, "b": "x"}


def test_resolve_parameters_references() -> None:
    results = {"quote": {"symbol": "AAPL", "price": 100.0}}
    resolved = _resolve_parameters(
        {"whole": "$quote", "field": "$quote.symbol"}, results
    )
    assert resolved == {"whole": {"symbol": "AAPL", "price": 100.0}, "field": "AAPL"}


def test_resolve_parameters_unknown_reference() -> None:
    with pytest.raises(ValueError):
        _resolve_parameters({"x": "$missing"}, {})


def test_resolve_parameters_unknown_field() -> None:
    with pytest.raises(ValueError):
        _resolve_parameters({"x": "$quote.nope"}, {"quote": {"symbol": "AAPL"}})


# ── Execution ────────────────────────────────────────────────────────────────


async def test_run_workflow_passes_outputs() -> None:
    workflow = Workflow(
        name="chained",
        steps=[
            WorkflowStep(
                tool_name="get_quote",
                parameters={"symbol": "AAPL"},
                output_key="quote",
            ),
            WorkflowStep(
                tool_name="get_fundamentals",
                parameters={"symbol": "$quote.symbol"},
                output_key="fundamentals",
            ),
        ],
    )
    result = await run_workflow(_market_provider(), workflow)
    assert set(result.step_results) == {"quote", "fundamentals"}
    assert "quote (get_quote)" in result.summary


async def test_run_workflow_unknown_tool() -> None:
    workflow = Workflow(
        name="bad",
        steps=[WorkflowStep(tool_name="not_a_tool", output_key="x")],
    )
    with pytest.raises(ValueError):
        await run_workflow(_market_provider(), workflow)


async def test_daily_market_check_end_to_end() -> None:
    workflow = get_workflow("daily_market_check")
    result = await run_workflow(_market_provider(), workflow)
    assert set(result.step_results) == {"market", "sectors", "rotation", "conviction"}
    conviction = result.step_results["conviction"]
    assert 0 <= conviction["conviction_score"] <= 100
    assert "recommended_exposure" in conviction


async def test_stock_research_workflow() -> None:
    workflow = get_workflow("stock_research", target="aapl")
    result = await run_workflow(_market_provider(), workflow)
    assert result.step_results["quote"]["symbol"] == "AAPL"


# ── Resolution and listing ───────────────────────────────────────────────────


def test_get_workflow_requires_target() -> None:
    with pytest.raises(ValueError):
        get_workflow("stock_research")
    with pytest.raises(ValueError):
        get_workflow("portfolio_rebalance_review")


def test_get_workflow_portfolio_builds_weights() -> None:
    workflow = get_workflow("portfolio_rebalance_review", target="aapl, msft")
    weights = workflow.steps[0].parameters["weights"]
    assert weights == {"AAPL": 0.5, "MSFT": 0.5}


def test_get_workflow_unknown_raises() -> None:
    with pytest.raises(ValueError):
        get_workflow("no_such_workflow")


def test_all_builtins_resolve() -> None:
    for name in BUILTIN_WORKFLOWS:
        target = "AAPL" if name in ("stock_research", "portfolio_rebalance_review") else ""
        workflow = get_workflow(name, target=target)
        assert workflow.steps


def test_list_workflows_builtin_and_custom() -> None:
    _write_custom_yaml("my_routine")
    names = {w["name"]: w["type"] for w in list_workflows()}
    assert names["daily_market_check"] == "builtin"
    assert names["my_routine"] == "custom"


# ── Custom YAML ──────────────────────────────────────────────────────────────


def _write_custom_yaml(name: str) -> None:
    ensure_dir(workflows_dir())
    (workflows_dir() / f"{name}.yaml").write_text(
        f"""
name: {name}
description: "Custom test workflow"
steps:
  - tool: get_quote
    parameters:
      symbol: AAPL
    output_key: quote
"""
    )


async def test_custom_workflow_roundtrip() -> None:
    _write_custom_yaml("custom_check")
    workflow = load_custom_workflow("custom_check")
    assert workflow.description == "Custom test workflow"
    result = await run_workflow(_market_provider(), workflow)
    assert result.step_results["quote"]["symbol"] == "AAPL"


def test_custom_workflow_missing_raises() -> None:
    with pytest.raises(ValueError):
        load_custom_workflow("ghost")


def test_custom_workflow_no_steps_raises() -> None:
    ensure_dir(workflows_dir())
    (workflows_dir() / "empty.yaml").write_text("name: empty\nsteps: []\n")
    with pytest.raises(ValueError):
        load_custom_workflow("empty")


async def test_run_workflow_reports_progress() -> None:
    from quantagent.utils.progress import set_progress_sink

    received: list[str] = []
    set_progress_sink(lambda call_id, text: received.append(text))
    try:
        workflow = get_workflow("stock_research", target="AAPL")
        await run_workflow(_market_provider(), workflow)
    finally:
        set_progress_sink(None)
    assert any("step 1/3" in msg for msg in received)
    assert any("quote done" in msg for msg in received)

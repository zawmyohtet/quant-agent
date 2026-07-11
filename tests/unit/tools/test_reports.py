"""Tests for the report generation framework."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from _synthetic import SyntheticProvider, make_ohlcv, trend_close
from pydantic import ValidationError

from quantagent.tools import screener
from quantagent.tools.reports import (
    Report,
    ReportSection,
    export_report_html,
    export_report_markdown,
    generate_market_daily,
    generate_portfolio_report,
    generate_screening_report,
    generate_sector_report,
    generate_stock_report,
    render_html,
    render_markdown,
)
from quantagent.tools.reports.base import df_to_markdown
from quantagent.tools.universe import SECTOR_ETFS

# ── Base: models, rendering, export ──────────────────────────────────────────


def _sample_report() -> Report:
    df = pd.DataFrame({"symbol": ["AAPL", "MSFT"], "price": [190.5, 420.25]})
    return Report(
        title="Sample Report",
        sections=[
            ReportSection(title="Intro", content="Some **markdown** text."),
            ReportSection(title="Data", tables=[df]),
        ],
        metadata={"type": "test"},
    )


def test_df_to_markdown_pipe_table() -> None:
    df = pd.DataFrame({"a": [1, None], "b": ["x", "y"]})
    md = df_to_markdown(df)
    assert md.startswith("| a | b |")
    assert "| x |" in md


def test_df_to_markdown_empty_and_truncation() -> None:
    assert df_to_markdown(pd.DataFrame()) == "_No data._"
    big = pd.DataFrame({"n": range(50)})
    md = df_to_markdown(big, max_rows=10)
    assert "40 more rows omitted" in md


def test_render_markdown_contains_sections_and_tables() -> None:
    md = render_markdown(_sample_report())
    assert "# Sample Report" in md
    assert "## Intro" in md
    assert "Some **markdown** text." in md
    assert "| symbol | price |" in md


def test_render_html_styled_page() -> None:
    html = render_html(_sample_report())
    assert "<title>Sample Report</title>" in html
    assert "<h2>Intro</h2>" in html
    assert "<table>" in html
    assert "<strong>markdown</strong>" in html


def test_export_files(tmp_path: Path) -> None:
    report = _sample_report()
    md_path = tmp_path / "out" / "r.md"
    html_path = tmp_path / "out" / "r.html"
    export_report_markdown(report, md_path)
    export_report_html(report, html_path)
    assert md_path.read_text().startswith("# Sample Report")
    assert "<table>" in html_path.read_text()


def test_report_section_frozen() -> None:
    section = ReportSection(title="X")
    with pytest.raises(ValidationError):
        section.title = "Y"  # type: ignore[misc]


# ── Generators ───────────────────────────────────────────────────────────────


def _full_provider() -> SyntheticProvider:
    frames: dict[str, pd.DataFrame] = {}
    for i, sym in enumerate(
        ["SPY", "QQQ", "DIA", "IWM", "RSP", "XLY", "XLP", "TLT", "HYG", "LQD"]
    ):
        frames[sym] = make_ohlcv(trend_close(n=300, drift=0.001, seed=i))
    for i, etf in enumerate(SECTOR_ETFS.values()):
        frames.setdefault(etf, make_ohlcv(trend_close(n=300, drift=0.001, seed=100 + i)))
    frames["^VIX"] = make_ohlcv(np.full(120, 14.0))
    frames["^VIX3M"] = make_ohlcv(np.full(120, 17.0))
    return SyntheticProvider(frames)


async def test_market_daily_report() -> None:
    report = await generate_market_daily(_full_provider())
    titles = [s.title for s in report.sections]
    assert titles == [
        "Market Overview", "Market Regime & Exposure", "Timing Signals",
        "Breadth", "Sentiment", "Sector Performance", "Sector Rotation",
        "Top Movers",
    ]
    regime = next(s for s in report.sections if s.title == "Market Regime & Exposure")
    assert "Recommended Exposure" in regime.content
    movers = next(s for s in report.sections if s.title == "Top Movers")
    assert "cache cold" in movers.content
    assert report.metadata["type"] == "market_daily"


async def test_sector_report(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(screener, "_fetch_universe_tickers", lambda universe: [])
    provider = _full_provider()
    report = await generate_sector_report(provider, "technology")
    assert report.metadata["sector"] == "Technology"
    titles = [s.title for s in report.sections]
    assert "Performance" in titles
    assert "Relative Strength" in titles
    perf = next(s for s in report.sections if s.title == "Performance")
    assert "Rank" in perf.content


async def test_sector_report_unknown_sector() -> None:
    with pytest.raises(ValueError):
        await generate_sector_report(_full_provider(), "cryptocurrencies")


async def test_stock_report() -> None:
    provider = _full_provider()
    provider.frames["AAPL"] = make_ohlcv(trend_close(n=300, drift=0.001, seed=7))
    report = await generate_stock_report(provider, "aapl")
    assert report.metadata["symbol"] == "AAPL"
    titles = [s.title for s in report.sections]
    assert titles == [
        "Company Overview", "Technical Analysis", "Fundamental Analysis",
        "Recent News",
    ]
    tech = next(s for s in report.sections if s.title == "Technical Analysis")
    assert "Rsi" in tech.content or "RSI" in tech.content


async def test_stock_report_degrades_on_missing_data() -> None:
    report = await generate_stock_report(_full_provider(), "MISSING")
    tech = next(s for s in report.sections if s.title == "Technical Analysis")
    assert "unavailable" in tech.content


async def test_portfolio_report() -> None:
    provider = _full_provider()
    provider.frames["AAA"] = make_ohlcv(trend_close(n=300, drift=0.002, seed=1))
    provider.frames["BBB"] = make_ohlcv(trend_close(n=300, drift=0.001, seed=2))
    provider.classifications = {
        "AAA": {"symbol": "AAA", "sector": "Technology", "industry": "Software"},
        "BBB": {"symbol": "BBB", "sector": "Healthcare", "industry": "Biotech"},
    }
    report = await generate_portfolio_report(provider, ["aaa", "bbb"])
    titles = [s.title for s in report.sections]
    assert titles == [
        "Allocation", "Risk Metrics", "Sector Exposure",
        "Optimization Suggestion", "Monte Carlo",
    ]
    allocation = report.sections[0].tables[0]
    assert allocation["weight"].sum() == pytest.approx(1.0)
    exposure = next(s for s in report.sections if s.title == "Sector Exposure")
    assert set(exposure.tables[0]["sector"]) == {"Technology", "Healthcare"}


async def test_portfolio_report_custom_weights_normalized() -> None:
    provider = _full_provider()
    provider.frames["AAA"] = make_ohlcv(trend_close(n=300, drift=0.002, seed=1))
    provider.frames["BBB"] = make_ohlcv(trend_close(n=300, drift=0.001, seed=2))
    report = await generate_portfolio_report(
        provider, ["AAA", "BBB"], weights={"AAA": 3.0, "BBB": 1.0}
    )
    allocation = report.sections[0].tables[0]
    assert allocation.set_index("symbol")["weight"]["AAA"] == 0.75


async def test_screening_report(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        screener, "_fetch_universe_tickers", lambda universe: ["MOMO", "WEAK"]
    )
    frames = {
        "MOMO": make_ohlcv(trend_close(n=300, drift=0.003)),
        "WEAK": make_ohlcv(trend_close(n=300, drift=-0.003)),
    }
    provider = SyntheticProvider(frames)
    report = await generate_screening_report(
        provider, screen_type="technical", criteria={"rsi_gt": 60}
    )
    params = report.sections[0]
    assert "Matches:** 1" in params.content
    results = report.sections[1]
    assert results.tables and results.tables[0]["symbol"].tolist() == ["MOMO"]


async def test_screening_report_unknown_type() -> None:
    with pytest.raises(ValueError):
        await generate_screening_report(_full_provider(), screen_type="astrology")


async def test_market_report_renders_end_to_end() -> None:
    report = await generate_market_daily(_full_provider())
    md = render_markdown(report)
    assert "Market Regime & Exposure" in md
    html = render_html(report)
    assert "<h2>Breadth</h2>" in html

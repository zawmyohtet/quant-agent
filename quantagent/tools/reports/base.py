"""Report models, rendering, and export.

Reports are structured (title + ordered sections, each with Markdown
content and optional DataFrames). Rendering goes through shared Jinja2
layout templates; section content is produced by the per-report
generators.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markdown_it import MarkdownIt
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"


class ReportConfig(BaseModel):
    """Options controlling report generation."""

    model_config = ConfigDict(frozen=True)
    title: str = ""
    format: str = "markdown"  # "markdown" | "html"
    date_range: str = "1y"
    benchmark: str = "SPY"


class ReportSection(BaseModel):
    """One report section: markdown content plus optional tables."""

    # arbitrary_types_allowed for pd.DataFrame fields
    # (precedent: BacktestResult in tools/backtesting.py).
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
    title: str
    content: str = ""
    tables: list[pd.DataFrame] = Field(default_factory=list)


class Report(BaseModel):
    """A complete generated report."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
    title: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sections: list[ReportSection] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def df_to_markdown(df: pd.DataFrame, max_rows: int = 30) -> str:
    """Render a DataFrame as a GitHub-style pipe table (no index)."""
    if df.empty:
        return "_No data._"
    view = df.head(max_rows)
    headers = [str(c) for c in view.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in view.itertuples(index=False):
        lines.append("| " + " | ".join(_format_cell(v) for v in row) + " |")
    if len(df) > max_rows:
        lines.append(f"\n_... {len(df) - max_rows} more rows omitted._")
    return "\n".join(lines)


def _format_cell(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, float):
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    return str(value)


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(_TEMPLATES_DIR),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _template_context(report: Report) -> dict:
    sections = [
        {
            "title": s.title,
            "content": s.content,
            "tables_md": [df_to_markdown(t) for t in s.tables],
        }
        for s in report.sections
    ]
    return {
        "title": report.title,
        "generated_at": report.generated_at.strftime("%Y-%m-%d %H:%M UTC"),
        "metadata": report.metadata,
        "sections": sections,
    }


def render_markdown(report: Report) -> str:
    """Render a report to Markdown via the shared layout template."""
    template = _environment().get_template("report.md.j2")
    return template.render(**_template_context(report))


def render_html(report: Report) -> str:
    """Render a report to a self-contained styled HTML page."""
    md = MarkdownIt("commonmark", {"html": False}).enable("table")
    context = _template_context(report)
    for section in context["sections"]:
        parts = [section["content"], *section["tables_md"]]
        section["html"] = md.render("\n\n".join(p for p in parts if p))
    template = _environment().get_template("report.html.j2")
    return template.render(**context)


def export_report_markdown(report: Report, path: Path) -> None:
    """Write the report as a Markdown file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(report))


def export_report_html(report: Report, path: Path) -> None:
    """Write the report as a styled HTML file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(report))

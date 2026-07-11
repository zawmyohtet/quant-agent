"""Report generation framework.

Structured reports (Pydantic models) rendered through Jinja2 layout
templates to Markdown or styled HTML. PDF export is intentionally not
included — it would pull in a heavy native dependency (weasyprint);
export HTML and print instead.
"""
from __future__ import annotations

from quantagent.tools.reports.base import (
    Report,
    ReportConfig,
    ReportSection,
    export_report_html,
    export_report_markdown,
    render_html,
    render_markdown,
)
from quantagent.tools.reports.market_report import generate_market_daily
from quantagent.tools.reports.portfolio_report import generate_portfolio_report
from quantagent.tools.reports.screening_report import generate_screening_report
from quantagent.tools.reports.sector_report import generate_sector_report
from quantagent.tools.reports.stock_report import generate_stock_report

__all__ = [
    "Report",
    "ReportConfig",
    "ReportSection",
    "export_report_html",
    "export_report_markdown",
    "render_html",
    "render_markdown",
    "generate_market_daily",
    "generate_portfolio_report",
    "generate_screening_report",
    "generate_sector_report",
    "generate_stock_report",
]

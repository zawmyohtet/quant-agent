"""Shared helpers for report generators."""
from __future__ import annotations

import logging
from collections.abc import Coroutine
from typing import Any

from quantagent.tools.reports.base import ReportSection
from quantagent.utils.progress import report_progress

logger = logging.getLogger(__name__)


async def safe_section(
    title: str, builder: Coroutine[Any, Any, ReportSection]
) -> ReportSection:
    """Run a section builder, degrading to a placeholder on failure.

    Reports must render even when one data source is down; each section
    is isolated so a single failure never kills the whole report.
    """
    report_progress(f"building report section: {title}…")
    try:
        return await builder
    except Exception as exc:
        logger.warning("Report section '%s' failed: %s", title, exc)
        return ReportSection(title=title, content=f"_Data unavailable ({exc})._")


def dict_lines(data: dict, keys: list[str] | None = None) -> str:
    """Format selected dict entries as markdown bullet lines."""
    selected = keys if keys is not None else list(data)
    lines = []
    for key in selected:
        value = data.get(key)
        if value is None:
            continue
        label = key.replace("_", " ").title()
        lines.append(f"- **{label}:** {_fmt(value)}")
    return "\n".join(lines)


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    if isinstance(value, dict):
        return ", ".join(f"{k}={_fmt(v)}" for k, v in value.items() if v is not None)
    if isinstance(value, list):
        return ", ".join(_fmt(v) for v in value) if value else "—"
    return str(value)

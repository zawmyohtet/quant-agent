"""Individual stock deep-dive report generator."""
from __future__ import annotations

import logging
from datetime import UTC, datetime

import pandas as pd

from quantagent.tools.providers.base import AbstractDataProvider
from quantagent.tools.reports._shared import dict_lines, safe_section
from quantagent.tools.reports.base import Report, ReportConfig, ReportSection
from quantagent.tools.technical import (
    detect_patterns,
    detect_support_resistance,
    summarize_technicals,
    wilder_rsi,
)

logger = logging.getLogger(__name__)


async def generate_stock_report(
    provider: AbstractDataProvider,
    symbol: str,
    config: ReportConfig | None = None,
) -> Report:
    """Generate a comprehensive single-stock report.

    Sections: company overview (quote + classification), technical
    analysis (summary, patterns, support/resistance), fundamentals,
    and recent news. DCF/F-Score are not auto-run — they need inputs
    (FCF projections, balance-sheet history) the report can't assume.

    Args:
        provider: Market data provider.
        symbol: Stock ticker symbol.
        config: Optional report options.
    """
    symbol = symbol.upper()
    config = config or ReportConfig()
    sections = [
        await safe_section("Company Overview", _overview_section(provider, symbol)),
        await safe_section(
            "Technical Analysis", _technical_section(provider, symbol, config.date_range)
        ),
        await safe_section("Fundamental Analysis", _fundamental_section(provider, symbol)),
        await safe_section("Recent News", _news_section(provider, symbol)),
    ]
    title = config.title or f"{symbol} Deep Dive — {datetime.now(UTC).date().isoformat()}"
    return Report(
        title=title, sections=sections, metadata={"type": "stock", "symbol": symbol}
    )


async def _overview_section(provider: AbstractDataProvider, symbol: str) -> ReportSection:
    quote = await provider.get_quote(symbol)
    classification = await provider.get_industry_classification(symbol)
    content = dict_lines(
        {
            "sector": classification.get("sector"),
            "industry": classification.get("industry"),
            "price": quote.get("price"),
            "change_percent": quote.get("change_percent"),
            "market_cap": quote.get("market_cap"),
            "volume": quote.get("volume"),
            "fifty_two_week_high": quote.get("fifty_two_week_high"),
            "fifty_two_week_low": quote.get("fifty_two_week_low"),
        }
    )
    return ReportSection(title="Company Overview", content=content)


async def _technical_section(
    provider: AbstractDataProvider, symbol: str, date_range: str
) -> ReportSection:
    df = await provider.get_ohlcv(symbol, period=date_range)
    summary = summarize_technicals(df)
    levels = detect_support_resistance(df)
    patterns = detect_patterns(df.iloc[-30:])
    parts = [
        dict_lines(summary),
        "\n**Key levels:**\n" + dict_lines(levels),
        "\n**RSI-14:** " + str(wilder_rsi(df["Close"])),
    ]
    if patterns:
        recent = ", ".join(
            f"{p['pattern']} ({p['date']})" for p in patterns[-3:]
        )
        parts.append(f"\n**Recent candlestick patterns:** {recent}")
    return ReportSection(title="Technical Analysis", content="\n".join(parts))


async def _fundamental_section(
    provider: AbstractDataProvider, symbol: str
) -> ReportSection:
    fundamentals = await provider.get_fundamentals(symbol)
    return ReportSection(title="Fundamental Analysis", content=dict_lines(fundamentals))


async def _news_section(provider: AbstractDataProvider, symbol: str) -> ReportSection:
    news = await provider.get_news(symbol, days=7)
    if not news:
        return ReportSection(title="Recent News", content="_No news in the last 7 days._")
    rows = [
        {
            "date": item.get("published_at", "")[:10],
            "title": item.get("title"),
            "source": item.get("source"),
        }
        for item in news[:10]
    ]
    return ReportSection(title="Recent News", tables=[pd.DataFrame(rows)])

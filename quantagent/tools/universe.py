"""Universe definitions and sector groupings.

Currently holds the built-in sector ETF map and cyclical/defensive
groupings shared by sector analysis, breadth, and regime tools.
Custom universe management (create/load/delete) lands with the
advanced screening milestone.
"""
from __future__ import annotations

SECTOR_ETFS: dict[str, str] = {
    "Technology": "XLK",
    "Healthcare": "XLV",
    "Financials": "XLF",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Communication Services": "XLC",
}

CYCLICAL_SECTORS: frozenset[str] = frozenset(
    {
        "Technology",
        "Consumer Discretionary",
        "Financials",
        "Industrials",
        "Materials",
        "Communication Services",
        "Energy",
        "Real Estate",
    }
)

DEFENSIVE_SECTORS: frozenset[str] = frozenset(
    {"Consumer Staples", "Utilities", "Healthcare"}
)

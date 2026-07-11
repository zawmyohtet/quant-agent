"""Universe definitions, constituent sourcing, and custom universe management.

Built-in universes: sp500, nasdaq100, dow30 (Wikipedia-scraped, cached
for 7 days under ~/.quantagent/cache/universes/) and sector_etfs
(local constant). Custom universes are JSON files under
~/.quantagent/universes/.

Note: russell2000 is intentionally not offered — there is no free,
reliable constituent source; it can return with a paid provider.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

from quantagent.tools._paths import cache_dir, ensure_dir, universes_dir

logger = logging.getLogger(__name__)

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

BUILTIN_UNIVERSES: list[str] = ["sp500", "nasdaq100", "dow30", "sector_etfs"]

_UNIVERSE_URLS: dict[str, str] = {
    "sp500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "nasdaq100": "https://en.wikipedia.org/wiki/Nasdaq-100",
    "dow30": "https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average",
}

_WIKI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

_CONSTITUENT_TTL = timedelta(days=7)
_NAME_PATTERN = re.compile(r"^[a-z0-9_\-]{1,64}$")


def _find_symbol_column(tables: list[pd.DataFrame]) -> list[str]:
    """Extract tickers from the first table containing a Symbol/Ticker column."""
    for table in tables:
        for col in ("Symbol", "Ticker", " ticker"):
            if col in table.columns:
                return list(table[col].dropna().astype(str).tolist())
    return []


_UNIVERSE_EXTRACTORS: dict[str, Callable[[list[pd.DataFrame]], list[str]]] = {
    "sp500": _find_symbol_column,
    "nasdaq100": _find_symbol_column,
    "dow30": _find_symbol_column,
}


def _scrape_constituents(name: str) -> list[str]:
    """Scrape universe constituents from Wikipedia."""
    url = _UNIVERSE_URLS[name]
    resp = requests.get(url, headers=_WIKI_HEADERS, timeout=30)
    resp.raise_for_status()
    tables = pd.read_html(StringIO(resp.text))
    return _UNIVERSE_EXTRACTORS[name](tables)


def _constituent_cache_path(name: str) -> Path:
    return cache_dir() / "universes" / f"{name}.json"


def _read_constituent_cache(name: str) -> tuple[list[str], bool]:
    """Return (cached symbols, is_fresh). Empty list when no cache exists."""
    path = _constituent_cache_path(name)
    if not path.exists():
        return [], False
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Corrupt constituent cache for %s: %s", name, exc)
        return [], False
    fetched_at = datetime.fromisoformat(payload["fetched_at"])
    fresh = datetime.now(UTC) - fetched_at <= _CONSTITUENT_TTL
    return payload["symbols"], fresh


def _write_constituent_cache(name: str, symbols: list[str]) -> None:
    path = _constituent_cache_path(name)
    ensure_dir(path.parent)
    path.write_text(
        json.dumps({"symbols": symbols, "fetched_at": datetime.now(UTC).isoformat()})
    )


def builtin_universe_symbols(name: str) -> list[str]:
    """Resolve a built-in universe to its symbols (scraped + cached 7 days).

    A stale cache is preferred over a hard failure when scraping breaks.

    Raises:
        ValueError: For unknown universe names.
    """
    if name == "sector_etfs":
        return list(SECTOR_ETFS.values())
    if name not in _UNIVERSE_URLS:
        raise ValueError(f"Unknown universe: {name}")
    cached, fresh = _read_constituent_cache(name)
    if cached and fresh:
        return cached
    try:
        symbols = _scrape_constituents(name)
    except Exception as exc:
        logger.warning("Failed to fetch %s constituents: %s", name, exc)
        return cached
    if symbols:
        _write_constituent_cache(name, symbols)
        return symbols
    return cached


# ── Custom universes ─────────────────────────────────────────────────────────


def _custom_universe_path(name: str) -> Path:
    return universes_dir() / f"{name}.json"


def _validate_name(name: str) -> None:
    if not _NAME_PATTERN.match(name):
        raise ValueError(
            "Universe names must be 1-64 chars of lowercase letters, digits, _ or -"
        )
    if name in BUILTIN_UNIVERSES:
        raise ValueError(f"'{name}' is a built-in universe and cannot be modified")


def list_universes() -> list[str]:
    """List all available universes (built-in first, then custom)."""
    custom = sorted(p.stem for p in universes_dir().glob("*.json"))
    return BUILTIN_UNIVERSES + custom


def create_universe(name: str, symbols: list[str]) -> None:
    """Save a custom universe to ``~/.quantagent/universes/<name>.json``.

    Symbols are uppercased and deduplicated (order preserved). Overwrites
    an existing custom universe of the same name (updates ``updated_at``).

    Raises:
        ValueError: For invalid names, built-in names, or empty symbols.
    """
    _validate_name(name)
    cleaned = list(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))
    if not cleaned:
        raise ValueError("A universe needs at least one symbol")
    path = _custom_universe_path(name)
    now = datetime.now(UTC).isoformat()
    created_at = now
    if path.exists():
        created_at = json.loads(path.read_text()).get("created_at", now)
    ensure_dir(path.parent)
    path.write_text(
        json.dumps(
            {"name": name, "symbols": cleaned, "created_at": created_at, "updated_at": now},
            indent=2,
        )
    )


def load_universe(name: str) -> list[str]:
    """Load a universe by name — built-in or custom.

    Raises:
        ValueError: When the universe does not exist.
    """
    if name in BUILTIN_UNIVERSES:
        return builtin_universe_symbols(name)
    path = _custom_universe_path(name)
    if not path.exists():
        raise ValueError(f"Unknown universe: {name}")
    payload = json.loads(path.read_text())
    return list(payload["symbols"])


def delete_universe(name: str) -> None:
    """Delete a custom universe.

    Raises:
        ValueError: For built-in names or missing universes.
    """
    _validate_name(name)
    path = _custom_universe_path(name)
    if not path.exists():
        raise ValueError(f"Unknown universe: {name}")
    path.unlink()


def get_universe_metadata(name: str) -> dict:
    """Return universe metadata: type, symbol count, timestamps."""
    if name in BUILTIN_UNIVERSES:
        return {
            "name": name,
            "type": "builtin",
            "symbol_count": len(builtin_universe_symbols(name)),
        }
    path = _custom_universe_path(name)
    if not path.exists():
        raise ValueError(f"Unknown universe: {name}")
    payload = json.loads(path.read_text())
    return {
        "name": name,
        "type": "custom",
        "symbol_count": len(payload["symbols"]),
        "created_at": payload.get("created_at"),
        "updated_at": payload.get("updated_at"),
    }

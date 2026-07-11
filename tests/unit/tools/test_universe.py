"""Tests for universe management and constituent sourcing."""
from __future__ import annotations

import pandas as pd
import pytest

from quantagent.tools import universe as universe_mod
from quantagent.tools.universe import (
    BUILTIN_UNIVERSES,
    SECTOR_ETFS,
    _find_symbol_column,
    builtin_universe_symbols,
    create_universe,
    delete_universe,
    get_universe_metadata,
    list_universes,
    load_universe,
)

# ── Custom universes ─────────────────────────────────────────────────────────


def test_create_load_roundtrip() -> None:
    create_universe("my-watchlist", ["aapl", "msft", "AAPL"])
    assert load_universe("my-watchlist") == ["AAPL", "MSFT"]


def test_list_includes_builtin_and_custom() -> None:
    create_universe("custom1", ["SPY"])
    names = list_universes()
    assert names[: len(BUILTIN_UNIVERSES)] == BUILTIN_UNIVERSES
    assert "custom1" in names


def test_delete_universe() -> None:
    create_universe("temp", ["SPY"])
    delete_universe("temp")
    with pytest.raises(ValueError):
        load_universe("temp")


def test_metadata_custom() -> None:
    create_universe("meta-test", ["SPY", "QQQ"])
    meta = get_universe_metadata("meta-test")
    assert meta["type"] == "custom"
    assert meta["symbol_count"] == 2
    assert meta["created_at"] is not None


def test_metadata_builtin() -> None:
    meta = get_universe_metadata("sector_etfs")
    assert meta == {"name": "sector_etfs", "type": "builtin", "symbol_count": 11}


def test_create_rejects_builtin_name() -> None:
    with pytest.raises(ValueError):
        create_universe("sp500", ["AAPL"])


def test_create_rejects_bad_name() -> None:
    with pytest.raises(ValueError):
        create_universe("Bad Name!", ["AAPL"])


def test_create_rejects_empty_symbols() -> None:
    with pytest.raises(ValueError):
        create_universe("empty", ["  "])


def test_delete_rejects_builtin() -> None:
    with pytest.raises(ValueError):
        delete_universe("nasdaq100")


def test_load_unknown_raises() -> None:
    with pytest.raises(ValueError):
        load_universe("does-not-exist")


def test_update_preserves_created_at() -> None:
    create_universe("evolving", ["SPY"])
    created = get_universe_metadata("evolving")["created_at"]
    create_universe("evolving", ["SPY", "QQQ"])
    meta = get_universe_metadata("evolving")
    assert meta["created_at"] == created
    assert meta["symbol_count"] == 2


# ── Built-in constituent sourcing ────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


_HTML = (
    "<table><thead><tr><th>Symbol</th><th>Security</th></tr></thead>"
    "<tbody><tr><td>AAPL</td><td>Apple</td></tr>"
    "<tr><td>MSFT</td><td>Microsoft</td></tr></tbody></table>"
)


def test_sector_etfs_resolve_locally() -> None:
    assert builtin_universe_symbols("sector_etfs") == list(SECTOR_ETFS.values())


def test_builtin_unknown_raises() -> None:
    with pytest.raises(ValueError):
        builtin_universe_symbols("russell2000")


def test_scrape_and_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def _get(url: str, headers: dict, timeout: int) -> _FakeResponse:
        calls["n"] += 1
        return _FakeResponse(_HTML)

    monkeypatch.setattr(universe_mod.requests, "get", _get)
    assert builtin_universe_symbols("sp500") == ["AAPL", "MSFT"]
    # Second call served from the constituent cache — no new request.
    assert builtin_universe_symbols("sp500") == ["AAPL", "MSFT"]
    assert calls["n"] == 1


def test_stale_cache_preferred_over_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        universe_mod.requests, "get", lambda url, headers, timeout: _FakeResponse(_HTML)
    )
    builtin_universe_symbols("dow30")

    def _boom(url: str, headers: dict, timeout: int) -> _FakeResponse:
        raise ConnectionError("offline")

    monkeypatch.setattr(universe_mod.requests, "get", _boom)
    monkeypatch.setattr(universe_mod, "_CONSTITUENT_TTL", universe_mod.timedelta(0))
    assert builtin_universe_symbols("dow30") == ["AAPL", "MSFT"]


def test_scrape_failure_no_cache_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(url: str, headers: dict, timeout: int) -> _FakeResponse:
        raise ConnectionError("offline")

    monkeypatch.setattr(universe_mod.requests, "get", _boom)
    assert builtin_universe_symbols("nasdaq100") == []


def test_find_symbol_column_scans_tables() -> None:
    tables = [
        pd.DataFrame({"Irrelevant": [1, 2]}),
        pd.DataFrame({"Ticker": ["NVDA", "AMD"]}),
    ]
    assert _find_symbol_column(tables) == ["NVDA", "AMD"]
    assert _find_symbol_column([pd.DataFrame({"X": [1]})]) == []

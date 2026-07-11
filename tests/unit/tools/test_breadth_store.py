"""Tests for the incremental breadth store."""
from __future__ import annotations

import pandas as pd
import pytest
from _synthetic import SyntheticProvider, make_ohlcv, trend_close

from quantagent.tools import breadth_store as store_mod
from quantagent.tools.breadth_store import BreadthStore
from quantagent.tools.universe import SECTOR_ETFS


def _etf_provider() -> SyntheticProvider:
    frames = {
        etf: make_ohlcv(trend_close(n=150, drift=0.001, seed=i))
        for i, etf in enumerate(SECTOR_ETFS.values())
    }
    return SyntheticProvider(frames)


async def test_cold_store_not_warm() -> None:
    assert await BreadthStore().is_warm("sector_etfs") is False


async def test_warm_up_ingests_and_marks_warm() -> None:
    store = BreadthStore()
    result = await store.warm_up(_etf_provider(), "sector_etfs")
    assert result["symbols"] == 11
    assert result["rows"] == 11 * 150
    assert await store.is_warm("sector_etfs") is True


async def test_load_field_wide_matrix() -> None:
    store = BreadthStore()
    await store.warm_up(_etf_provider(), "sector_etfs")
    closes = await store.load_field("sector_etfs", "close")
    assert closes.shape == (150, 11)
    assert isinstance(closes.index, pd.DatetimeIndex)
    volumes = await store.load_field("sector_etfs", "volume", days=10)
    assert len(volumes) == 10


async def test_load_field_rejects_unknown_field() -> None:
    with pytest.raises(ValueError):
        await BreadthStore().load_field("sector_etfs", "open")


async def test_load_field_empty_universe() -> None:
    assert (await BreadthStore().load_field("sector_etfs", "close")).empty


async def test_ensure_cold_without_warmup_returns_false() -> None:
    ready = await BreadthStore().ensure(
        _etf_provider(), "sector_etfs", allow_warmup=False
    )
    assert ready is False


async def test_ensure_warms_when_allowed() -> None:
    store = BreadthStore()
    ready = await store.ensure(_etf_provider(), "sector_etfs", allow_warmup=True)
    assert ready is True
    assert await store.is_warm("sector_etfs") is True


async def test_update_refreshes_known_symbols() -> None:
    store = BreadthStore()
    provider = _etf_provider()
    await store.warm_up(provider, "sector_etfs")
    result = await store.update(provider, "sector_etfs")
    assert result["symbols"] == 11


async def test_warm_up_unknown_universe_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(store_mod, "load_universe", lambda name: [])
    with pytest.raises(ValueError):
        await BreadthStore().warm_up(_etf_provider(), "sp500")

"""Tests for the local data cache."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from quantagent.tools.cache import DataCache


def _cache(tmp_path: Path) -> DataCache:
    return DataCache(db_path=tmp_path / "cache.db")


async def test_set_get_json_roundtrip(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    await cache.set("universe:sp500", ["AAPL", "MSFT"], ttl=60)
    assert await cache.get("universe:sp500") == ["AAPL", "MSFT"]


async def test_set_get_dict_roundtrip(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    await cache.set("quote:AAPL", {"price": 190.5, "volume": 1000}, ttl=60)
    assert await cache.get("quote:AAPL") == {"price": 190.5, "volume": 1000}


async def test_set_get_dataframe_roundtrip(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    dates = pd.date_range("2024-01-01", periods=5, freq="D", tz="UTC")
    df = pd.DataFrame({"Close": [1.0, 2.0, 3.0, 4.0, 5.0]}, index=dates)
    await cache.set("ohlcv:AAPL", df, ttl=60)
    restored = await cache.get("ohlcv:AAPL")
    assert isinstance(restored, pd.DataFrame)
    assert restored["Close"].tolist() == df["Close"].tolist()
    assert isinstance(restored.index, pd.DatetimeIndex)
    assert str(restored.index.tz) == "UTC"


async def test_get_missing_key(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    assert await cache.get("nope") is None


async def test_expired_entry_returns_none(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    await cache.set("stale", "value", ttl=-1)
    assert await cache.get("stale") is None


async def test_set_overwrites(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    await cache.set("key", "old", ttl=60)
    await cache.set("key", "new", ttl=60)
    assert await cache.get("key") == "new"


async def test_invalidate(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    await cache.set("key", "value", ttl=60)
    await cache.invalidate("key")
    assert await cache.get("key") is None


async def test_clear(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    await cache.set("a", 1, ttl=60)
    await cache.set("b", 2, ttl=60)
    await cache.clear()
    assert await cache.get("a") is None
    assert await cache.get("b") is None


async def test_default_path_uses_quantagent_home(
    tmp_path: Path, monkeypatch: object
) -> None:
    cache = DataCache()
    await cache.set("key", "value", ttl=60)
    assert await cache.get("key") == "value"

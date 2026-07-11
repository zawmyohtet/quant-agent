"""Tests for the yfinance batch download frame splitting."""
from __future__ import annotations

import pandas as pd

from quantagent.tools.providers.yfinance_provider import (
    _normalize_ohlcv_frame,
    _split_batch_frame,
)

_OHLCV_COLS = ["Open", "High", "Low", "Close", "Volume"]


def _single_frame(n: int = 5) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame({col: [100.0] * n for col in _OHLCV_COLS}, index=dates)


def _multi_frame(symbols: list[str], n: int = 5) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    columns = pd.MultiIndex.from_product([symbols, _OHLCV_COLS])
    data = {(sym, col): [100.0] * n for sym in symbols for col in _OHLCV_COLS}
    return pd.DataFrame(data, index=dates, columns=columns)


def test_split_multi_ticker_frame() -> None:
    raw = _multi_frame(["AAPL", "MSFT"])
    result = _split_batch_frame(raw, ["AAPL", "MSFT"])
    assert set(result) == {"AAPL", "MSFT"}
    for df in result.values():
        assert list(df.columns) == _OHLCV_COLS
        assert str(df.index.tz) == "UTC"
        assert df.index.name == "Date"


def test_split_missing_symbol_omitted() -> None:
    raw = _multi_frame(["AAPL"])
    result = _split_batch_frame(raw, ["AAPL", "MISSING"])
    assert set(result) == {"AAPL"}


def test_split_single_ticker_flat_columns() -> None:
    raw = _single_frame()
    result = _split_batch_frame(raw, ["AAPL"])
    assert set(result) == {"AAPL"}
    assert list(result["AAPL"].columns) == _OHLCV_COLS


def test_split_empty_frame() -> None:
    assert _split_batch_frame(pd.DataFrame(), ["AAPL"]) == {}


def test_normalize_drops_all_nan_rows() -> None:
    frame = _single_frame()
    frame.iloc[2] = float("nan")
    result = _normalize_ohlcv_frame(frame)
    assert result is not None
    assert len(result) == 4


def test_normalize_preserves_tz_aware_index() -> None:
    frame = _single_frame()
    frame.index = pd.DatetimeIndex(frame.index).tz_localize("America/New_York")
    result = _normalize_ohlcv_frame(frame)
    assert result is not None
    assert str(result.index.tz) == "UTC"


def test_normalize_rejects_non_ohlcv_frame() -> None:
    frame = pd.DataFrame({"Other": [1.0]})
    assert _normalize_ohlcv_frame(frame) is None


async def test_industry_classification_reads_info(monkeypatch) -> None:
    import quantagent.tools.providers.yfinance_provider as mod

    class _FakeTicker:
        def __init__(self, symbol: str) -> None:
            self.info = {"sector": "Technology", "industry": "Software"}

    monkeypatch.setattr(mod.yf, "Ticker", _FakeTicker)
    provider = mod.YFinanceProvider()
    result = await provider.get_industry_classification("MSFT")
    assert result == {"symbol": "MSFT", "sector": "Technology", "industry": "Software"}

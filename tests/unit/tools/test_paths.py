"""Tests for shared filesystem paths."""
from __future__ import annotations

from pathlib import Path

import pytest

from quantagent.tools import _paths


def test_quantagent_home_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QUANTAGENT_HOME", str(tmp_path / "qa"))
    assert _paths.quantagent_home() == tmp_path / "qa"
    assert _paths.cache_dir() == tmp_path / "qa" / "cache"
    assert _paths.universes_dir() == tmp_path / "qa" / "universes"
    assert _paths.workflows_dir() == tmp_path / "qa" / "workflows"
    assert _paths.trades_db_path() == tmp_path / "qa" / "trades.db"


def test_quantagent_home_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUANTAGENT_HOME", raising=False)
    assert _paths.quantagent_home() == Path.home() / ".quantagent"


def test_ensure_dir_creates(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir"
    assert _paths.ensure_dir(target) == target
    assert target.is_dir()

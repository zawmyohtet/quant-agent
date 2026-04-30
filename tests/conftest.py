"""Global pytest fixtures for the QuantAgent test suite."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def patch_quantagent_config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect ~/.quantagent/config.toml to a temp path so tests never override user config."""
    import quantagent.tui.config as config_mod

    monkeypatch.setattr(
        config_mod, "_DEFAULT_CONFIG_PATH", tmp_path / "config.toml"
    )

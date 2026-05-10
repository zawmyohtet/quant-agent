from __future__ import annotations

from pathlib import Path

import pytest

from quantagent.tui.config import QuantAgentConfig


class TestQuantAgentConfig:
    def test_defaults(self) -> None:
        cfg = QuantAgentConfig()
        assert cfg.model == "anthropic:claude-sonnet-4-6"
        assert cfg.provider == "yfinance"
        assert cfg.theme == "dark"
        assert "run_backtest" in cfg.approval_required
        assert cfg.zai_api_key is None
        assert cfg.zai_api_base == "https://api.z.ai/api/paas/v4/"

    def test_load_save_roundtrip(self, tmp_path: Path) -> None:
        cfg = QuantAgentConfig(model="openai:gpt-4o", provider="polygon")
        path = tmp_path / "config.toml"
        # Patch the default path temporarily
        import quantagent.tui.config as config_mod

        original_path = config_mod._DEFAULT_CONFIG_PATH
        config_mod._DEFAULT_CONFIG_PATH = path
        try:
            cfg.save()
            loaded = QuantAgentConfig.load()
            assert loaded.model == "openai:gpt-4o"
            assert loaded.provider == "polygon"
        finally:
            config_mod._DEFAULT_CONFIG_PATH = original_path

    def test_load_applies_zai_env_values(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import quantagent.tui.config as config_mod

        monkeypatch.setattr(config_mod, "_DEFAULT_CONFIG_PATH", tmp_path / "config.toml")
        monkeypatch.setenv("ZAI_API_KEY", "zai-test-key")
        monkeypatch.setenv("ZAI_API_BASE", "https://example.test/v1/")

        loaded = QuantAgentConfig.load()

        assert loaded.zai_api_key == "zai-test-key"
        assert loaded.zai_api_base == "https://example.test/v1/"

    def test_save_excludes_zai_api_key(self, tmp_path: Path) -> None:
        cfg = QuantAgentConfig(zai_api_key="secret-zai-key")
        path = tmp_path / "config.toml"

        import quantagent.tui.config as config_mod

        original_path = config_mod._DEFAULT_CONFIG_PATH
        config_mod._DEFAULT_CONFIG_PATH = path
        try:
            cfg.save()
            content = path.read_text()
            assert "zai_api_key" not in content
            assert "secret-zai-key" not in content
        finally:
            config_mod._DEFAULT_CONFIG_PATH = original_path

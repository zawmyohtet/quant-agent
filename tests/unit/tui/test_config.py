from __future__ import annotations

from pathlib import Path

from quantagent.tui.config import QuantAgentConfig


class TestQuantAgentConfig:
    def test_defaults(self) -> None:
        cfg = QuantAgentConfig()
        assert cfg.model == "anthropic:claude-sonnet-4-6"
        assert cfg.provider == "yfinance"
        assert cfg.theme == "dark"
        assert "run_backtest" in cfg.approval_required

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

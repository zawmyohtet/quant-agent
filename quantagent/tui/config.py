from __future__ import annotations

import logging
import os
from pathlib import Path

import toml
from pydantic import BaseModel, Field
from pydantic.config import ConfigDict

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_DIR = Path.home() / ".quantagent"
_DEFAULT_CONFIG_PATH = _DEFAULT_CONFIG_DIR / "config.toml"
_DEFAULT_ZAI_BASE_URL = "https://api.z.ai/api/paas/v4/"


class QuantAgentConfig(BaseModel):
    """Persisted user configuration for QuantAgent."""

    model_config = ConfigDict(extra="ignore")

    model: str = Field(default="anthropic:claude-sonnet-4-6")
    provider: str = Field(default="yfinance")
    theme: str = Field(default="dark")
    approval_required: list[str] = Field(
        default_factory=lambda: ["run_backtest", "optimize_portfolio"]
    )
    thread_id: str | None = Field(default=None)
    zai_api_key: str | None = Field(default=None, exclude=True)
    zai_api_base: str = Field(default=_DEFAULT_ZAI_BASE_URL)

    # Skills
    extra_skill_dirs: list[str] = Field(default_factory=list)
    disabled_skills: list[str] = Field(default_factory=list)

    @classmethod
    def load(cls) -> QuantAgentConfig:
        """Load configuration from disk, or return defaults."""
        if _DEFAULT_CONFIG_PATH.exists():
            try:
                data = toml.load(_DEFAULT_CONFIG_PATH)
                return cls(**data)._with_env_overrides()
            except Exception:
                logger.warning("Failed to load config from %s", _DEFAULT_CONFIG_PATH)
        return cls()._with_env_overrides()

    def save(self) -> None:
        """Persist configuration to disk."""
        _DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        _DEFAULT_CONFIG_PATH.write_text(toml.dumps(self.model_dump()))

    def _with_env_overrides(self) -> QuantAgentConfig:
        """Return config with secret/env-only model provider values applied."""
        return self.model_copy(
            update={
                "zai_api_key": self.zai_api_key or os.environ.get("ZAI_API_KEY"),
                "zai_api_base": os.environ.get("ZAI_API_BASE", self.zai_api_base),
            }
        )


def load_dotenv_file() -> None:
    """Load API keys from ~/.quantagent/.env if present."""
    env_path = _DEFAULT_CONFIG_DIR / ".env"
    if env_path.exists():
        from dotenv import load_dotenv

        load_dotenv(dotenv_path=env_path, override=False)

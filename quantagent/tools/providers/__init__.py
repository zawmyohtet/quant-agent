"""Data provider implementations for QuantAgent."""
from __future__ import annotations

import logging
from pathlib import Path

from quantagent.tools.providers.alpha_vantage import AlphaVantageProvider
from quantagent.tools.providers.base import AbstractDataProvider
from quantagent.tools.providers.polygon import PolygonProvider
from quantagent.tools.providers.yfinance_provider import YFinanceProvider
from quantagent.tui.config import QuantAgentConfig

logger = logging.getLogger(__name__)


def get_active_provider(config: QuantAgentConfig) -> AbstractDataProvider:
    """Resolve the active data provider from configuration."""
    match config.provider:
        case "yfinance":
            return YFinanceProvider()
        case "alpha_vantage":
            api_key = _get_api_key("ALPHA_VANTAGE")
            return AlphaVantageProvider(api_key=api_key)
        case "polygon":
            api_key = _get_api_key("POLYGON")
            return PolygonProvider(api_key=api_key)
        case _:
            raise ValueError(f"Unknown provider: {config.provider}")


def _get_api_key(prefix: str) -> str:
    """Load API key from environment or ~/.quantagent/.env."""
    from dotenv import load_dotenv

    env_path = Path.home() / ".quantagent" / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)

    import os

    key = os.environ.get(f"{prefix}_API_KEY", "")
    if not key:
        logger.warning("%s_API_KEY not found in environment", prefix)
    return key

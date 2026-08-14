from __future__ import annotations

from unittest.mock import patch

from quantagent.agent.graph import _create_chat_model, _parse_model_string
from quantagent.tui.config import QuantAgentConfig


def test_parse_model_string_zai() -> None:
    model_name, provider = _parse_model_string("zai:glm-5.1")
    assert model_name == "glm-5.1"
    assert provider == "zai"


def test_create_chat_model_zai_uses_openai_compatible_base_url() -> None:
    with patch(
        "quantagent.agent.graph.init_chat_model",
        return_value=object(),
    ) as mock_init:
        _create_chat_model(
            QuantAgentConfig(model="zai:glm-5.1", zai_api_key="test-zai-key")
        )

    mock_init.assert_called_once_with(
        model="glm-5.1",
        model_provider="openai",
        api_key="test-zai-key",
        base_url="https://api.z.ai/api/paas/v4/",
    )


def test_parse_model_string_opencode() -> None:
    model_name, provider = _parse_model_string("opencode:kimi-k3")
    assert model_name == "kimi-k3"
    assert provider == "opencode"


def test_create_chat_model_opencode_uses_openai_compatible_base_url() -> None:
    with patch(
        "quantagent.agent.graph.init_chat_model",
        return_value=object(),
    ) as mock_init:
        _create_chat_model(
            QuantAgentConfig(model="opencode:kimi-k3", opencode_api_key="test-opencode-key")
        )

    mock_init.assert_called_once_with(
        model="kimi-k3",
        model_provider="openai",
        api_key="test-opencode-key",
        base_url="https://opencode.ai/zen/go/v1/",
    )


def test_create_chat_model_non_zai_passthrough() -> None:
    with patch(
        "quantagent.agent.graph.init_chat_model",
        return_value=object(),
    ) as mock_init:
        _create_chat_model(QuantAgentConfig(model="anthropic:claude-sonnet-4-6"))

    mock_init.assert_called_once_with(
        "claude-sonnet-4-6",
        model_provider="anthropic",
    )

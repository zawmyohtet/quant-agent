from __future__ import annotations

from unittest.mock import patch

from quantagent.agent.graph import _create_chat_model, _parse_model_string


def test_parse_model_string_zai() -> None:
    model_name, provider = _parse_model_string("zai:glm-5.1")
    assert model_name == "glm-5.1"
    assert provider == "zai"


def test_create_chat_model_zai_uses_openai_compatible_base_url() -> None:
    with patch(
        "quantagent.agent.graph.init_chat_model",
        return_value=object(),
    ) as mock_init:
        _create_chat_model("zai:glm-5.1")

    mock_init.assert_called_once_with(
        model="glm-5.1",
        model_provider="openai",
        api_key=None,
        base_url="https://api.z.ai/api/paas/v4/",
    )


def test_create_chat_model_non_zai_passthrough() -> None:
    with patch(
        "quantagent.agent.graph.init_chat_model",
        return_value=object(),
    ) as mock_init:
        _create_chat_model("anthropic:claude-sonnet-4-6")

    mock_init.assert_called_once_with(
        "claude-sonnet-4-6",
        model_provider="anthropic",
    )

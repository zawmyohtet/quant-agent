from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from quantagent.agent import graph as graph_module
from quantagent.agent.graph import _create_chat_model, _parse_model_string, _stage_resolved_skills
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


@pytest.fixture
def staging_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the skills staging directory into a temp dir for isolation."""
    staging = tmp_path / ".resolved-skills"
    monkeypatch.setattr(graph_module, "_SKILLS_STAGING_DIR", staging)
    return staging


def _make_skill_dir(tmp_path: Path, name: str) -> Path:
    skill_dir = tmp_path / "source" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {name}\ndescription: test\n---\n")
    return skill_dir


def test_stage_resolved_skills_creates_symlinks_deepagents_can_scan(
    tmp_path: Path, staging_dir: Path
) -> None:
    """deepagents expects `sources` to contain subdirectories with SKILL.md —
    verify the staged directory has exactly that shape."""
    skill_a = _make_skill_dir(tmp_path, "skill-a")
    skill_b = _make_skill_dir(tmp_path, "skill-b")

    result = _stage_resolved_skills([str(skill_a), str(skill_b)])

    assert result == staging_dir
    staged_names = {p.name for p in staging_dir.iterdir()}
    assert staged_names == {"skill-a", "skill-b"}
    for name, source in [("skill-a", skill_a), ("skill-b", skill_b)]:
        staged = staging_dir / name
        assert staged.is_symlink()
        assert staged.resolve() == source.resolve()
        assert (staged / "SKILL.md").exists()


def test_stage_resolved_skills_rebuilds_from_scratch_each_call(
    tmp_path: Path, staging_dir: Path
) -> None:
    """A skill removed from the resolved list (e.g. disabled) must not linger
    as a stale symlink from a previous call."""
    skill_a = _make_skill_dir(tmp_path, "skill-a")
    skill_b = _make_skill_dir(tmp_path, "skill-b")

    _stage_resolved_skills([str(skill_a), str(skill_b)])
    _stage_resolved_skills([str(skill_a)])

    assert {p.name for p in staging_dir.iterdir()} == {"skill-a"}


def test_stage_resolved_skills_handles_empty_list(staging_dir: Path) -> None:
    result = _stage_resolved_skills([])

    assert result == staging_dir
    assert list(staging_dir.iterdir()) == []

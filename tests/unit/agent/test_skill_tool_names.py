"""Regression test: skill allowed-tools must match registered tool names.

Skills reference agent tools by name in their frontmatter; a rename in
tools_registry silently breaks the skill unless this test catches it.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from quantagent.agent.tools_registry import build_tool_registry
from quantagent.tui.config import QuantAgentConfig

_SKILLS_DIR = Path(__file__).parents[3] / "skills"


def _skill_files() -> list[Path]:
    return sorted(_SKILLS_DIR.glob("*/SKILL.md"))


def _allowed_tools(skill_file: Path) -> list[str]:
    frontmatter = yaml.safe_load(skill_file.read_text().split("---")[1])
    raw = str(frontmatter.get("allowed-tools", ""))
    return [name.strip() for name in raw.split(",") if name.strip()]


@pytest.fixture(scope="module")
def registered_tool_names() -> set[str]:
    tools = build_tool_registry(QuantAgentConfig(provider="yfinance"))
    return {tool.name for tool in tools}


def test_skills_exist() -> None:
    assert len(_skill_files()) >= 12


@pytest.mark.parametrize("skill_file", _skill_files(), ids=lambda p: p.parent.name)
def test_skill_allowed_tools_are_registered(
    skill_file: Path, registered_tool_names: set[str]
) -> None:
    unknown = [t for t in _allowed_tools(skill_file) if t not in registered_tool_names]
    assert not unknown, (
        f"{skill_file.parent.name}: allowed-tools reference unregistered tools "
        f"{unknown} — fix the skill or the registry"
    )


def test_approval_defaults_are_registered(registered_tool_names: set[str]) -> None:
    config = QuantAgentConfig()
    unknown = [t for t in config.approval_required if t not in registered_tool_names]
    assert not unknown, f"approval_required references unregistered tools: {unknown}"

"""Tests for SkillResolver."""
from __future__ import annotations

from pathlib import Path

from quantagent.agent.skills import SkillResolver


def test_builtin_skills_all_discovered():
    resolver = SkillResolver()
    resolved = resolver.resolve()
    assert "backtesting" in resolved.skill_names
    assert "risk-framework" in resolved.skill_names
    assert "indicator-playbook" in resolved.skill_names
    assert "strategy-patterns" in resolved.skill_names
    assert "data-sources" in resolved.skill_names


def test_user_skill_overrides_builtin_same_name(tmp_path: Path):
    user_risk = tmp_path / "risk-framework"
    user_risk.mkdir()
    (user_risk / "SKILL.md").write_text(
        "---\nname: risk-framework\ndescription: My risk rules.\n---\n# My Risk"
    )
    resolver = SkillResolver(extra_skill_dirs=[tmp_path])
    resolved = resolver.resolve()
    # risk-framework appears only once
    assert resolved.skill_names.count("risk-framework") == 1
    # the user version (extra dir) wins — it appears last in skill_dirs
    assert str(tmp_path / "risk-framework") in resolved.skill_dirs


def test_new_user_skill_appended(tmp_path: Path):
    options = tmp_path / "options-flow"
    options.mkdir()
    (options / "SKILL.md").write_text(
        "---\nname: options-flow\ndescription: Options flow.\n---\n# Options"
    )
    resolver = SkillResolver(extra_skill_dirs=[tmp_path])
    resolved = resolver.resolve()
    assert "options-flow" in resolved.skill_names
    assert resolved.source_map["options-flow"] == "custom"


def test_disabled_skill_excluded():
    resolver = SkillResolver(disabled_skills=["indicator-playbook"])
    resolved = resolver.resolve()
    assert "indicator-playbook" not in resolved.skill_names
    assert "backtesting" in resolved.skill_names  # others unaffected


def test_missing_user_skills_dir_handled_gracefully():
    # ~/.quantagent/skills/ may not exist on a fresh install
    resolver = SkillResolver()
    resolved = resolver.resolve()  # must not raise
    assert len(resolved.skill_dirs) > 0


def test_list_all_includes_description():
    resolver = SkillResolver()
    listing = resolver.list_all()
    backtesting = next(s for s in listing if s["name"] == "backtesting")
    assert len(backtesting["description"]) > 0


def test_skill_dir_without_skill_md_ignored(tmp_path: Path):
    bad_dir = tmp_path / "not-a-skill"
    bad_dir.mkdir()
    # No SKILL.md inside
    resolver = SkillResolver(extra_skill_dirs=[tmp_path])
    resolved = resolver.resolve()
    assert "not-a-skill" not in resolved.skill_names

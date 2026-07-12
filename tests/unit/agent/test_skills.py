"""Tests for SkillResolver."""
from __future__ import annotations

from pathlib import Path

import pytest

from quantagent.agent.skills import SkillResolver


def test_builtin_skills_all_discovered() -> None:
    resolver = SkillResolver()
    resolved = resolver.resolve()
    assert "backtesting" in resolved.skill_names
    assert "risk-framework" in resolved.skill_names
    assert "indicator-playbook" in resolved.skill_names
    assert "strategy-patterns" in resolved.skill_names
    assert "data-sources" in resolved.skill_names


def test_user_skill_overrides_builtin_same_name(tmp_path: Path) -> None:
    user_risk = tmp_path / "risk-framework"
    user_risk.mkdir()
    (user_risk / "SKILL.md").write_text(
        "---\nname: risk-framework\ndescription: My risk rules.\n---\n# My Risk"
    )
    resolver = SkillResolver(extra_skill_dirs=[tmp_path])
    resolved = resolver.resolve()
    assert resolved.skill_names.count("risk-framework") == 1
    assert str(tmp_path / "risk-framework") in resolved.skill_dirs


def test_new_user_skill_appended(tmp_path: Path) -> None:
    options = tmp_path / "options-flow"
    options.mkdir()
    (options / "SKILL.md").write_text(
        "---\nname: options-flow\ndescription: Options flow.\n---\n# Options"
    )
    resolver = SkillResolver(extra_skill_dirs=[tmp_path])
    resolved = resolver.resolve()
    assert "options-flow" in resolved.skill_names
    assert resolved.source_map["options-flow"] == "custom"


def test_disabled_skill_excluded() -> None:
    resolver = SkillResolver(disabled_skills=["indicator-playbook"])
    resolved = resolver.resolve()
    assert "indicator-playbook" not in resolved.skill_names
    assert "backtesting" in resolved.skill_names


def test_missing_user_skills_dir_handled_gracefully() -> None:
    resolver = SkillResolver()
    resolved = resolver.resolve()
    assert len(resolved.skill_dirs) > 0


def test_list_all_includes_description() -> None:
    resolver = SkillResolver()
    listing = resolver.list_all()
    backtesting = next(s for s in listing if s["name"] == "backtesting")
    assert len(backtesting["description"]) > 0


def test_skill_dir_without_skill_md_ignored(tmp_path: Path) -> None:
    bad_dir = tmp_path / "not-a-skill"
    bad_dir.mkdir()
    resolver = SkillResolver(extra_skill_dirs=[tmp_path])
    resolved = resolver.resolve()
    assert "not-a-skill" not in resolved.skill_names


def test_read_description_no_frontmatter(tmp_path: Path) -> None:
    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# Just Content\nNo frontmatter here.")
    resolver = SkillResolver(extra_skill_dirs=[tmp_path])
    listing = resolver.list_all()
    entry = next(s for s in listing if s["name"] == "test-skill")
    assert entry["description"] == ""


def test_read_description_unclosed_frontmatter(tmp_path: Path) -> None:
    skill_dir = tmp_path / "test-skill-2"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: test-skill-2\ndescription: Unclosed\n")
    resolver = SkillResolver(extra_skill_dirs=[tmp_path])
    listing = resolver.list_all()
    entry = next(s for s in listing if s["name"] == "test-skill-2")
    assert entry["description"] == ""


def test_read_description_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    skill_dir = tmp_path / "test-skill-3"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text("---\nname: test-skill-3\ndescription: Gone\n---")

    def _bad_read(*args: object, **kwargs: object) -> str:
        raise OSError("permission denied")

    monkeypatch.setattr(skill_md.__class__, "read_text", _bad_read)
    resolver = SkillResolver(extra_skill_dirs=[tmp_path])
    listing = resolver.list_all()
    entry = next(s for s in listing if s["name"] == "test-skill-3")
    assert entry["description"] == ""

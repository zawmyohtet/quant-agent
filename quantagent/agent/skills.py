"""SkillResolver — path resolution and override logic."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Built-in skills shipped inside the package
BUILTIN_SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"

# User personal skills
USER_SKILLS_DIR = Path.home() / ".quantagent" / "skills"


@dataclass(frozen=True)
class ResolvedSkills:
    """Result of skill resolution — paths ready to pass to create_deep_agent."""

    skill_dirs: list[str]          # Ordered list of skill source dirs (as str paths)
    skill_names: list[str]         # Discovered skill names for /skills command display
    source_map: dict[str, str]     # skill_name -> source label ("built-in" | "user" | "custom")


class SkillResolver:
    """
    Resolves skill source directories and metadata following deepagents source precedence:
    built-in -> user personal -> extra (last wins for same-named skills).

    Does NOT parse SKILL.md — that is deepagents' responsibility via progressive disclosure.
    This class only manages which directories are passed to create_deep_agent.
    """

    def __init__(
        self,
        extra_skill_dirs: list[Path] | None = None,
        disabled_skills: list[str] | None = None,
    ):
        self.extra_skill_dirs = extra_skill_dirs or []
        self.disabled_skills = set(disabled_skills or [])

    def resolve(self) -> ResolvedSkills:
        """
        Discover all skill directories and return them in precedence order.
        Sources: built-in -> user -> extra dirs (last wins per deepagents spec).
        Skills in disabled_skills are excluded from all sources.
        """
        # Collect skill dirs from each source in ascending precedence order
        builtin_skills = self._scan_skill_dirs(BUILTIN_SKILLS_DIR, source_label="built-in")
        user_skills = self._scan_skill_dirs(USER_SKILLS_DIR, source_label="user")
        extra_skills: dict[str, tuple[Path, str]] = {}
        for extra_dir in self.extra_skill_dirs:
            extra_skills.update(self._scan_skill_dirs(extra_dir, source_label="custom"))

        # Merge: later sources override earlier ones for the same skill name (last wins)
        merged: dict[str, tuple[Path, str]] = {}
        merged.update(builtin_skills)
        merged.update(user_skills)
        merged.update(extra_skills)

        # Apply disabled filter
        active = {
            name: (path, source)
            for name, (path, source) in merged.items()
            if name not in self.disabled_skills
        }

        skill_dirs = [str(path) for path, _ in active.values()]
        skill_names = list(active.keys())
        source_map = {name: source for name, (_, source) in active.items()}

        return ResolvedSkills(
            skill_dirs=skill_dirs,
            skill_names=skill_names,
            source_map=source_map,
        )

    def list_all(self) -> list[dict]:
        """
        Return metadata for all discovered skills across all sources for /skills command.
        Reads only the frontmatter name and description from each SKILL.md.
        Returns [{name, source, path, description}].
        """
        resolved = self.resolve()
        results = []
        for name in resolved.skill_names:
            source = resolved.source_map[name]
            skill_dir = next(
                Path(d) for d in resolved.skill_dirs if Path(d).name == name
            )
            skill_md = skill_dir / "SKILL.md"
            description = self._read_description(skill_md)
            results.append({
                "name": name,
                "source": source,
                "path": str(skill_dir),
                "description": description,
            })
        return results

    # -- Internal helpers ---------------------------------------------------

    def _scan_skill_dirs(
        self, root: Path, source_label: str
    ) -> dict[str, tuple[Path, str]]:
        """Return {skill_name: (skill_dir_path, source_label)} for all valid skill dirs."""
        if not root.exists():
            return {}
        result = {}
        for skill_dir in sorted(root.iterdir()):
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                result[skill_dir.name] = (skill_dir, source_label)
            else:
                logger.debug("Skipping %s — not a valid skill directory", skill_dir)
        return result

    def _read_description(self, skill_md: Path) -> str:
        """
        Read only the description from SKILL.md frontmatter.
        Returns empty string if the file cannot be parsed.
        """
        try:
            raw = skill_md.read_text(encoding="utf-8")
            if not raw.startswith("---"):
                return ""
            end = raw.find("---", 3)
            if end == -1:
                return ""
            frontmatter = raw[3:end]
            for line in frontmatter.splitlines():
                if line.startswith("description:"):
                    return line.partition(":")[2].strip().strip('"').strip("'")
            return ""
        except OSError:
            return ""

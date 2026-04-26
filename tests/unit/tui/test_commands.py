from __future__ import annotations

from quantagent.tui.commands import REGISTRY, find_command


class TestSlashCommands:
    def test_all_commands_have_unique_names(self) -> None:
        names = [cmd.name for cmd in REGISTRY]
        assert len(names) == len(set(names))

    def test_find_command_existing(self) -> None:
        cmd = find_command("help")
        assert cmd is not None
        assert cmd.name == "help"

    def test_find_command_missing(self) -> None:
        assert find_command("nonexistent") is None

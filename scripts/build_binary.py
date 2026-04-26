#!/usr/bin/env python3
"""Build a standalone binary using PyInstaller."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ENTRY = '''\
from quantagent.main import app

if __name__ == "__main__":
    app()
'''


def main() -> None:
    """Generate a temporary entry script and invoke PyInstaller."""
    entry_path = Path("build_entry.py")
    entry_path.write_text(_ENTRY)
    try:
        cmd = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--onefile",
            "--name",
            "quantagent",
            "--collect-data",
            "vectorbt",
            "--collect-data",
            "sklearn",
            "--copy-metadata",
            "imageio",
            "--copy-metadata",
            "vectorbt",
            "--copy-metadata",
            "scikit-learn",
            "--copy-metadata",
            "langchain",
            "--copy-metadata",
            "langgraph",
            "--copy-metadata",
            "pandas",
            "--copy-metadata",
            "numpy",
            "--hidden-import",
            "pkgutil",
            str(entry_path),
        ]
        subprocess.run(cmd, check=True)
        print("Binary built at: dist/quantagent")
    finally:
        entry_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()

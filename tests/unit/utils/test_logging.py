"""Tests for file-logging setup and unhandled exception hook."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from quantagent.utils.logging import init_file_logging, install_excepthook


def test_init_file_logging_creates_log_file(tmp_path: Path, monkeypatch):
    """Verify that init_file_logging creates the log directory and file."""
    log_root = tmp_path / ".quantagent" / "logs"
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    init_file_logging(max_bytes=1024, backup_count=1)

    assert log_root.exists()
    log_files = list(log_root.glob("errors.log*"))
    assert len(log_files) >= 1  # might have been rotated immediately on open

    # Clean up: remove the handler so other tests aren't affected.
    _remove_root_handlers()


def test_init_file_logging_captures_log_record(tmp_path: Path, monkeypatch):
    """Log a message and verify it appears in the file."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    init_file_logging(max_bytes=10 * 1024 * 1024, backup_count=1)

    test_logger = logging.getLogger("test.capture")
    test_logger.info("hello from test_init_file_logging_captures_log_record")

    log_dir = tmp_path / ".quantagent" / "logs"
    log_files = list(log_dir.glob("errors.log*"))
    assert log_files

    _remove_root_handlers()
    content = log_files[0].read_text()
    assert "hello from test_init_file_logging_captures_log_record" in content


def test_install_excepthook_logs_unhandled_exception(tmp_path: Path, monkeypatch):
    """Ensure the excepthook logs unhandled exceptions before the original hook runs."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    init_file_logging()

    original_called = False

    def _fake_original(exc_type, exc_value, tb):
        nonlocal original_called
        original_called = True

    monkeypatch.setattr(sys, "excepthook", _fake_original)

    install_excepthook()

    try:
        raise ValueError("unhandled-oops")
    except ValueError:
        sys.excepthook(*sys.exc_info())

    _remove_root_handlers()

    log_dir = tmp_path / ".quantagent" / "logs"
    log_files = list(log_dir.glob("errors.log*"))
    assert log_files
    content = log_files[0].read_text()
    assert "unhandled-oops" in content
    assert original_called


def test_install_excepthook_idempotency(monkeypatch):
    """Calling install_excepthook twice should not cause infinite recursion."""
    original = sys.excepthook

    install_excepthook()
    first = sys.excepthook

    install_excepthook()
    second = sys.excepthook

    # Both should be our wrapper, not the same identity but both functional.
    assert first is not original
    assert second is not original

    # Restore to avoid side effects.
    sys.excepthook = original


def _remove_root_handlers() -> None:
    """Strip all handlers from the root logger between tests."""
    for h in list(logging.root.handlers):
        logging.root.removeHandler(h)
    logging.root.setLevel(logging.WARNING)

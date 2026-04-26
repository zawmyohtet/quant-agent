from __future__ import annotations

from quantagent.tui.config import QuantAgentConfig
from quantagent.tui.session_state import SessionState


class TestSessionState:
    def test_new_thread_generates_id(self) -> None:
        cfg = QuantAgentConfig()
        state = SessionState(config=cfg)
        old_id = state.thread_id
        state.new_thread()
        assert state.thread_id != old_id
        assert state.token_count == 0
        assert cfg.thread_id == state.thread_id

    def test_config_thread_id_restored(self) -> None:
        cfg = QuantAgentConfig(thread_id="test-thread-123")
        state = SessionState(config=cfg)
        assert state.thread_id == "test-thread-123"

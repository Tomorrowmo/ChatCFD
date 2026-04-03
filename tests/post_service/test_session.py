import time
from unittest.mock import patch

from post_service.session import SessionManager, SessionState


class TestSessionState:
    def test_init(self):
        state = SessionState("s1")
        assert state.session_id == "s1"
        assert state.post_data is None
        assert state.output_dir is None
        assert state.created_at <= time.time()
        assert state.last_active <= time.time()

    def test_touch_updates_last_active(self):
        state = SessionState("s1")
        old = state.last_active
        # Ensure measurable time difference
        time.sleep(0.01)
        state.touch()
        assert state.last_active > old


class TestSessionManager:
    def test_create(self):
        mgr = SessionManager()
        state = mgr.create("s1")
        assert isinstance(state, SessionState)
        assert state.session_id == "s1"

    def test_get_existing(self):
        mgr = SessionManager()
        mgr.create("s1")
        state = mgr.get("s1")
        assert state is not None
        assert state.session_id == "s1"

    def test_get_nonexistent_returns_none(self):
        mgr = SessionManager()
        assert mgr.get("no_such_id") is None

    def test_get_touches_session(self):
        mgr = SessionManager()
        mgr.create("s1")
        old = mgr.get("s1").last_active
        time.sleep(0.01)
        state = mgr.get("s1")
        assert state.last_active > old

    def test_destroy(self):
        mgr = SessionManager()
        mgr.create("s1")
        mgr.destroy("s1")
        assert mgr.get("s1") is None

    def test_destroy_clears_post_data(self):
        mgr = SessionManager()
        state = mgr.create("s1")
        state.post_data = object()  # simulate a PostData reference
        mgr.destroy("s1")
        assert state.post_data is None

    def test_destroy_nonexistent_is_noop(self):
        mgr = SessionManager()
        mgr.destroy("no_such_id")  # should not raise

    def test_multiple_sessions_isolated(self):
        mgr = SessionManager()
        s1 = mgr.create("s1")
        s2 = mgr.create("s2")
        s1.output_dir = "/path/a"
        s2.output_dir = "/path/b"
        assert mgr.get("s1").output_dir == "/path/a"
        assert mgr.get("s2").output_dir == "/path/b"
        mgr.destroy("s1")
        assert mgr.get("s1") is None
        assert mgr.get("s2") is not None

    def test_cleanup_expired(self):
        mgr = SessionManager(timeout_seconds=1)
        mgr.create("old")
        mgr.create("new")
        # Artificially age the "old" session
        mgr._sessions["old"].last_active = time.time() - 2
        mgr.cleanup_expired()
        assert mgr.get("old") is None
        assert mgr.get("new") is not None

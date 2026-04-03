"""Tests for agent.session.AgentSession and SessionPool."""

import time

from agent.session import AgentSession, SessionPool


class TestAgentSession:
    def test_init_defaults(self):
        s = AgentSession("s1")
        assert s.session_id == "s1"
        assert s.messages == []
        assert s.user_confirmed_coding is False
        assert s.created_at <= time.time()
        assert s.last_active <= time.time()

    def test_touch_updates_last_active(self):
        s = AgentSession("s1")
        old = s.last_active
        time.sleep(0.01)
        s.touch()
        assert s.last_active > old


class TestSessionPool:
    def test_create(self):
        pool = SessionPool()
        s = pool.create("s1")
        assert isinstance(s, AgentSession)
        assert s.session_id == "s1"

    def test_get_existing(self):
        pool = SessionPool()
        pool.create("s1")
        s = pool.get("s1")
        assert s is not None
        assert s.session_id == "s1"

    def test_get_nonexistent(self):
        pool = SessionPool()
        assert pool.get("nope") is None

    def test_get_or_create_new(self):
        pool = SessionPool()
        s = pool.get_or_create("s1")
        assert s.session_id == "s1"

    def test_get_or_create_existing(self):
        pool = SessionPool()
        s1 = pool.create("s1")
        s2 = pool.get_or_create("s1")
        assert s1 is s2

    def test_destroy(self):
        pool = SessionPool()
        pool.create("s1")
        pool.destroy("s1")
        assert pool.get("s1") is None

    def test_destroy_nonexistent_no_error(self):
        pool = SessionPool()
        pool.destroy("nope")  # should not raise

    def test_user_confirmed_coding_default_false(self):
        pool = SessionPool()
        s = pool.get_or_create("s1")
        assert s.user_confirmed_coding is False

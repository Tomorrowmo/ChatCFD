"""AgentSession and SessionPool — per-session state management."""

import time


class AgentSession:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.messages: list[dict] = []
        self.user_confirmed_coding: bool = False
        self.created_at: float = time.time()
        self.last_active: float = time.time()

    def touch(self):
        self.last_active = time.time()


class SessionPool:
    def __init__(self):
        self._sessions: dict[str, AgentSession] = {}

    def get(self, session_id: str) -> AgentSession | None:
        s = self._sessions.get(session_id)
        if s:
            s.touch()
        return s

    def create(self, session_id: str) -> AgentSession:
        s = AgentSession(session_id)
        self._sessions[session_id] = s
        return s

    def get_or_create(self, session_id: str) -> AgentSession:
        return self.get(session_id) or self.create(session_id)

    def destroy(self, session_id: str):
        self._sessions.pop(session_id, None)

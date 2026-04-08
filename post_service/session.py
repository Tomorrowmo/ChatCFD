import time


class SessionState:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.post_data = None       # PostData instance, set after loadFile
        self.output_dir = None      # auto-set to file's directory
        self.geometry_results = {}  # result_id -> vtkDataSet (geometry algorithm outputs)
        self.created_at = time.time()
        self.last_active = time.time()

    def touch(self):
        self.last_active = time.time()


class SessionManager:
    def __init__(self, timeout_seconds: int = 3600):
        self._sessions = {}
        self._timeout = timeout_seconds

    def create(self, session_id: str) -> SessionState:
        state = SessionState(session_id)
        self._sessions[session_id] = state
        return state

    def get(self, session_id: str):
        state = self._sessions.get(session_id)
        if state:
            state.touch()
        return state

    def destroy(self, session_id: str):
        state = self._sessions.pop(session_id, None)
        if state and state.post_data:
            state.post_data = None

    def cleanup_expired(self):
        now = time.time()
        expired = [sid for sid, s in self._sessions.items()
                   if now - s.last_active > self._timeout]
        for sid in expired:
            self.destroy(sid)

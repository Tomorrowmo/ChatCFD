import time


class SessionState:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self._post_data_map = {}    # file_path -> PostData
        self._active_file = None    # current active file path
        self.output_dir = None      # auto-set to file's directory
        self.geometry_results = {}  # result_id -> vtkDataSet (geometry algorithm outputs)
        self.created_at = time.time()
        self.last_active = time.time()

    @property
    def post_data(self):
        """Active file's PostData (backward compatible)."""
        if self._active_file:
            return self._post_data_map.get(self._active_file)
        return None

    @post_data.setter
    def post_data(self, value):
        if value is None:
            self._active_file = None
        else:
            self._active_file = value.file_path
            self._post_data_map[value.file_path] = value

    def get_post_data(self, file_path=None):
        """Get PostData for a specific file, or active file if None."""
        if file_path:
            # Normalize for lookup
            import os
            normalized = os.path.normpath(file_path).replace("\\", "/")
            return self._post_data_map.get(normalized)
        return self.post_data

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
        if state:
            state._post_data_map.clear()
            state._active_file = None

    def cleanup_expired(self):
        now = time.time()
        expired = [sid for sid, s in self._sessions.items()
                   if now - s.last_active > self._timeout]
        for sid in expired:
            self.destroy(sid)

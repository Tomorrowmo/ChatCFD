"""MCP tool: loadFile — Load a CFD data file and return its summary."""


def register(mcp, engine):
    @mcp.tool()
    def loadFile(file_path: str, session_id: str = "default") -> dict:
        """Load a CFD data file and return its summary."""
        return engine.load_file(session_id, file_path)

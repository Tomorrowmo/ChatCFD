"""MCP tool: listFiles — List available files in a directory."""


def register(mcp, engine):
    @mcp.tool()
    def listFiles(directory: str = ".", suffix: str = "") -> dict:
        """List available files in a directory."""
        return engine.list_files(directory, suffix or None)

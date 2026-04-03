"""MCP tool: compare — Compare data from two or more sources (zones, files, CSV)."""


def register(mcp, engine):
    @mcp.tool()
    def compare(source_a: str, source_b: str, session_id: str = "default") -> dict:
        """Compare data from two or more sources (zones, files, CSV)."""
        return engine.compare(session_id, source_a, source_b)

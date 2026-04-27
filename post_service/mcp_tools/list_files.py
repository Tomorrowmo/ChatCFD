"""MCP tool: listFiles — List available files in a directory."""


def register(mcp, engine):
    @mcp.tool()
    def listFiles(directory: str = ".", suffix: str = "",
                  keyword: str = "", recursive: bool = False) -> dict:
        """List files in a directory. Set recursive=true to search subdirectories.
        Use keyword to filter by filename (case-insensitive partial match).
        Example: listFiles("D:/XField/data", suffix=".cgns", keyword="x37b", recursive=true)"""
        return engine.list_files(
            directory, suffix or None, keyword or None, recursive,
        )

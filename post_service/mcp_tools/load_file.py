"""MCP tool: loadFile — Load CFD data file(s) and return summary."""


def register(mcp, engine):
    @mcp.tool()
    def loadFile(file_path: str, session_id: str = "default") -> dict:
        """Load a CFD data file or all supported files in a directory.

        file_path can be:
        - A single file path: loads that file
        - A directory path: scans and loads ALL supported CFD files in that directory

        Supported formats: .cgns, .cga, .plt, .dat, .case, .vtm, .vts, .vtu, .vtp, d3plot, controlDict (OpenFOAM).

        When loading a directory, returns summaries for all loaded files.
        Each file becomes available for independent analysis (zone browsing, calculations, etc.).
        """
        return engine.load_file(session_id, file_path)

"""MCP tool: exportData — Export data to a file (CSV, VTM, image)."""

import json


def register(mcp, engine):
    @mcp.tool()
    def exportData(zone: str, scalars: str = "[]", format: str = "csv", session_id: str = "default") -> dict:
        """Export data to a file (CSV, VTM, image)."""
        parsed_scalars = json.loads(scalars)
        return engine.export_data(session_id, zone, parsed_scalars, format)

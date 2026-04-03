"""MCP tool: calculate — Run a calculation on the loaded file and return numerical results."""

import json


def register(mcp, engine):
    @mcp.tool()
    def calculate(method: str, params: str = "{}", zone_name: str = "", session_id: str = "default") -> dict:
        """Run a calculation on the loaded file and return numerical results."""
        parsed_params = json.loads(params)
        return engine.calculate(session_id, method, parsed_params, zone_name)

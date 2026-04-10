"""MCP tool: calculate — Run a calculation on the loaded file and return numerical results."""

import json


def register(mcp, engine):
    @mcp.tool()
    def calculate(method: str, params: str = "{}", zone_name: str = "", session_id: str = "default") -> dict:
        """Run a calculation on the loaded file and return numerical results."""
        print(f"[MCP.calculate] method={method}, params={params!r}, zone_name={zone_name!r}, session_id={session_id!r}")
        parsed_params = json.loads(params)
        result = engine.calculate(session_id, method, parsed_params, zone_name)
        print(f"[MCP.calculate] result keys: {list(result.keys()) if isinstance(result, dict) else type(result)}")
        return result

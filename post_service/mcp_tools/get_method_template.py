"""MCP tool: getMethodTemplate — Show available methods or parameters for a specific method."""


def register(mcp, engine):
    @mcp.tool()
    def getMethodTemplate(method: str = "") -> dict:
        """Show available methods or parameters for a specific method."""
        return engine.get_method_template(method or None)

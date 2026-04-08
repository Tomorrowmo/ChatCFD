"""MCP Client Pool — connects to multiple MCP servers (SSE + stdio)."""

import asyncio
import json

import nest_asyncio
nest_asyncio.apply()  # Allow asyncio.run() inside existing event loop (uvicorn)

from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp import ClientSession, StdioServerParameters


# Mempalace tools exposed to LLM (4 of 21).
# The rest are called internally by agent code, never shown to LLM.
MEMPALACE_LLM_TOOLS = {
    "mempalace_search",
    "mempalace_add_drawer",
    "mempalace_kg_query",
    "mempalace_kg_add",
}


class MCPClient:
    """Single MCP server connection (SSE or stdio)."""

    def __init__(self, name: str, transport: str, url: str = "",
                 command: str = "", args: list[str] | None = None):
        self.name = name
        self.transport = transport          # "sse" or "stdio"
        self.url = url                      # for SSE
        self.command = command              # for stdio
        self.args = args or []              # for stdio
        self._tools_raw: list[dict] = []
        self._tool_names: set[str] = set()

    def load_tools(self):
        """Fetch available tools from the MCP server."""
        async def _load():
            if self.transport == "sse":
                async with sse_client(self.url) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.list_tools()
                        self._store_tools(result.tools)
            else:
                server_params = StdioServerParameters(
                    command=self.command, args=self.args,
                )
                async with stdio_client(server_params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.list_tools()
                        self._store_tools(result.tools)

        try:
            asyncio.run(_load())
        except Exception as e:
            print(f"[MCP:{self.name}] Failed to load tools: {e}")

    def call_tool(self, name: str, arguments: dict) -> str:
        """Call a single MCP tool and return its text result."""
        async def _call():
            if self.transport == "sse":
                async with sse_client(self.url) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.call_tool(name, arguments)
                        return result.content[0].text if result.content else "{}"
            else:
                server_params = StdioServerParameters(
                    command=self.command, args=self.args,
                )
                async with stdio_client(server_params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.call_tool(name, arguments)
                        return result.content[0].text if result.content else "{}"

        try:
            return asyncio.run(_call())
        except Exception as e:
            return json.dumps({"error": f"MCP call [{self.name}] failed: {e}"})

    def _store_tools(self, tools):
        self._tools_raw = []
        self._tool_names = set()
        for tool in tools:
            self._tool_names.add(tool.name)
            self._tools_raw.append({
                "name": tool.name,
                "description": tool.description or "",
                "inputSchema": tool.inputSchema or {},
            })


class MCPClientPool:
    """Multi-server MCP pool with tool routing and filtering."""

    def __init__(self):
        self._clients: dict[str, MCPClient] = {}
        self._tool_route: dict[str, str] = {}   # tool_name -> client_name

    def add_client(self, client: MCPClient):
        self._clients[client.name] = client

    def load_all_tools(self):
        """Load tools from all registered MCP servers."""
        for client in self._clients.values():
            client.load_tools()
            for name in client._tool_names:
                self._tool_route[name] = client.name
        names = list(self._tool_route.keys())
        print(f"[MCPPool] {len(names)} tools from {len(self._clients)} servers: {names}")

    def call_tool(self, name: str, arguments: dict) -> str:
        """Route tool call to the correct MCP server."""
        client_name = self._tool_route.get(name)
        if not client_name:
            return json.dumps({"error": f"Unknown tool: {name}"})
        return self._clients[client_name].call_tool(name, arguments)

    def has_tool(self, name: str) -> bool:
        return name in self._tool_route

    def get_tools_for_llm(self) -> list[dict]:
        """Return tools for LLM, with mempalace tools filtered to whitelist."""
        tools = []
        for client in self._clients.values():
            for t in client._tools_raw:
                if client.name != "mempalace":
                    tools.append(self._to_openai_format(t))
                elif t["name"] in MEMPALACE_LLM_TOOLS:
                    tools.append(self._to_openai_format(t))
        return tools

    @staticmethod
    def _to_openai_format(t: dict) -> dict:
        return {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["inputSchema"],
            },
        }

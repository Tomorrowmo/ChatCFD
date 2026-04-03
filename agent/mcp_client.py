"""MCP Client — connects to post_service via SSE."""

import asyncio
import json

import nest_asyncio
nest_asyncio.apply()  # Allow asyncio.run() inside existing event loop (uvicorn)

from mcp.client.sse import sse_client
from mcp import ClientSession


class MCPClient:
    def __init__(self, mcp_url: str = "http://127.0.0.1:8000/mcp/sse"):
        self.mcp_url = mcp_url
        self._tools_raw: list[dict] = []
        self._tool_names: set[str] = set()

    def load_tools(self):
        """Fetch available tools from the MCP server."""
        async def _load():
            async with sse_client(self.mcp_url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    self._tools_raw = []
                    self._tool_names = set()
                    for tool in result.tools:
                        self._tool_names.add(tool.name)
                        self._tools_raw.append({
                            "name": tool.name,
                            "description": tool.description or "",
                            "inputSchema": tool.inputSchema or {},
                        })

        try:
            asyncio.run(_load())
        except Exception as e:
            print(f"[MCP] Failed to load tools: {e}")

    def call_tool(self, name: str, arguments: dict) -> str:
        """Call a single MCP tool and return its text result."""
        async def _call():
            async with sse_client(self.mcp_url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(name, arguments)
                    return result.content[0].text if result.content else "{}"

        try:
            return asyncio.run(_call())
        except Exception as e:
            return json.dumps({"error": f"MCP call failed: {e}"})

    def get_tools_for_llm(self) -> list[dict]:
        """Return tool definitions in OpenAI function-calling format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["inputSchema"],
                },
            }
            for t in self._tools_raw
        ]

    def has_tool(self, name: str) -> bool:
        return name in self._tool_names

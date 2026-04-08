"""MCP Client Pool — connects to multiple MCP servers (SSE + stdio)."""

import asyncio
import json
import subprocess
import sys

import nest_asyncio
nest_asyncio.apply()  # Allow asyncio.run() inside existing event loop (uvicorn)

from mcp.client.sse import sse_client
from mcp import ClientSession


# Mempalace tools exposed to LLM (4 of 21).
MEMPALACE_LLM_TOOLS = {
    "mempalace_search",
    "mempalace_add_drawer",
    "mempalace_kg_query",
    "mempalace_kg_add",
}

# Mempalace has a fixed tool set — register without connecting.
_MEMPALACE_TOOL_DEFS = [
    {"name": "mempalace_search", "description": "Semantic search across stored memories", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}, "wing": {"type": "string"}, "room": {"type": "string"}}, "required": ["query"]}},
    {"name": "mempalace_add_drawer", "description": "Store a memory into the palace", "inputSchema": {"type": "object", "properties": {"wing": {"type": "string"}, "room": {"type": "string"}, "content": {"type": "string"}, "source_file": {"type": "string"}}, "required": ["wing", "room", "content"]}},
    {"name": "mempalace_kg_query", "description": "Query knowledge graph for entity relationships", "inputSchema": {"type": "object", "properties": {"entity": {"type": "string"}, "as_of": {"type": "string"}, "direction": {"type": "string"}}, "required": ["entity"]}},
    {"name": "mempalace_kg_add", "description": "Add a fact to the knowledge graph", "inputSchema": {"type": "object", "properties": {"subject": {"type": "string"}, "predicate": {"type": "string"}, "object": {"type": "string"}, "valid_from": {"type": "string"}}, "required": ["subject", "predicate", "object"]}},
    {"name": "mempalace_check_duplicate", "description": "", "inputSchema": {}},
    {"name": "mempalace_kg_invalidate", "description": "", "inputSchema": {}},
    {"name": "mempalace_status", "description": "", "inputSchema": {}},
    {"name": "mempalace_list_wings", "description": "", "inputSchema": {}},
    {"name": "mempalace_list_rooms", "description": "", "inputSchema": {}},
    {"name": "mempalace_kg_timeline", "description": "", "inputSchema": {}},
    {"name": "mempalace_diary_write", "description": "", "inputSchema": {}},
    {"name": "mempalace_diary_read", "description": "", "inputSchema": {}},
]


def _stdio_jsonrpc_call(command: str, args: list[str],
                        method: str, params: dict, req_id: int = 1) -> dict:
    """Call a stdio MCP server via direct subprocess + JSON-RPC.

    Bypasses MCP SDK's async stdio_client which conflicts with uvicorn's
    event loop on Windows. Spawns a fresh subprocess per call.
    """
    # Build JSON-RPC messages
    init_msg = json.dumps({
        "jsonrpc": "2.0", "id": 0, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "chatcfd", "version": "1.0"},
        },
    })
    call_msg = json.dumps({
        "jsonrpc": "2.0", "id": req_id, "method": method, "params": params,
    })
    stdin_data = init_msg + "\n" + call_msg + "\n"

    try:
        proc = subprocess.run(
            [command] + args,
            input=stdin_data, capture_output=True, text=True,
            timeout=15,
        )
        # Parse responses — one per line, find the one matching our req_id
        for line in proc.stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                resp = json.loads(line)
                if resp.get("id") == req_id and "result" in resp:
                    return resp["result"]
            except json.JSONDecodeError:
                continue
        return {"error": f"No valid response. stderr: {proc.stderr[:200]}"}
    except subprocess.TimeoutExpired:
        return {"error": "stdio call timed out (15s)"}
    except Exception as e:
        return {"error": f"stdio call failed: {e}"}


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

    async def async_load_tools(self):
        """Fetch available tools from the MCP server (async, SSE only)."""
        async with sse_client(self.url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                self._store_tools(result.tools)

    def call_tool(self, name: str, arguments: dict) -> str:
        """Call a single MCP tool and return its text result."""
        if self.transport == "sse":
            async def _call():
                async with sse_client(self.url) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.call_tool(name, arguments)
                        return result.content[0].text if result.content else "{}"
            try:
                return asyncio.run(_call())
            except BaseException as e:
                cause = e
                while hasattr(cause, 'exceptions') and cause.exceptions:
                    cause = cause.exceptions[0]
                return json.dumps({"error": f"MCP call [{self.name}] failed: {cause}"})
        else:
            # stdio: use direct subprocess to avoid async event loop conflicts
            result = _stdio_jsonrpc_call(
                self.command, self.args,
                method="tools/call",
                params={"name": name, "arguments": arguments},
            )
            # Extract text from MCP response format
            content = result.get("content", [])
            if isinstance(content, list) and content:
                return content[0].get("text", json.dumps(result))
            if "error" in result:
                return json.dumps(result)
            return json.dumps(result)

    def register_tools(self, tool_defs: list[dict]):
        """Register tools from static definitions (no server connection needed)."""
        self._tools_raw = tool_defs
        self._tool_names = {t["name"] for t in tool_defs}

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
        # SSE clients: load dynamically
        async def _load_sse():
            for client in self._clients.values():
                if client.transport != "sse":
                    continue
                try:
                    await client.async_load_tools()
                    print(f"[MCPPool] {client.name}: {len(client._tool_names)} tools loaded")
                except BaseException as e:
                    cause = e
                    while hasattr(cause, 'exceptions') and cause.exceptions:
                        cause = cause.exceptions[0]
                    print(f"[MCPPool] {client.name}: failed — {type(cause).__name__}: {cause}")

        try:
            asyncio.run(_load_sse())
        except BaseException as e:
            cause = e
            while hasattr(cause, 'exceptions') and cause.exceptions:
                cause = cause.exceptions[0]
            print(f"[MCPPool] SSE load failed: {type(cause).__name__}: {cause}")

        # stdio clients: register static tool defs, verify with a test call
        for client in self._clients.values():
            if client.transport == "stdio":
                client.register_tools(_MEMPALACE_TOOL_DEFS)
                # Quick connectivity test
                test = _stdio_jsonrpc_call(
                    client.command, client.args,
                    method="tools/list", params={},
                )
                if "error" in test:
                    print(f"[MCPPool] {client.name}: registered (static), connectivity FAILED: {test['error']}")
                else:
                    n = len(test.get("tools", []))
                    print(f"[MCPPool] {client.name}: {n} tools verified (stdio)")

        # Build routing table
        for client in self._clients.values():
            for name in client._tool_names:
                self._tool_route[name] = client.name
        print(f"[MCPPool] {len(self._tool_route)} tools from {len(self._clients)} servers")

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

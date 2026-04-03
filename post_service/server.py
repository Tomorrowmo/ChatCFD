"""ChatCFD server entry point: wires FastAPI + FastMCP + PostEngine."""

import os

import uvicorn
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

from post_service.engine import PostEngine
from post_service.mcp_tools import register_all as register_mcp_tools
from post_service.http_api import setup_all as setup_http_api

# Resolve algorithms directory relative to this file
_ALGORITHMS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "algorithms")
).replace("\\", "/")

# Core engine
engine = PostEngine(algorithms_dir=_ALGORITHMS_DIR)

# FastMCP server
mcp = FastMCP("ChatCFD")
register_mcp_tools(mcp, engine)

# FastAPI app
app = FastAPI(title="ChatCFD")

# Mount MCP SSE transport at /mcp
sse_app = mcp.sse_app()
app.mount("/mcp", sse_app)

# Register HTTP API routes
setup_http_api(app, engine)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

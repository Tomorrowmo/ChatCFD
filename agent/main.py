"""ChatCFD Agent Service — WebSocket server + CLI fallback."""

import json
import os

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from agent.mcp_client import MCPClient
from agent.harness import Harness
from agent.session import SessionPool
from agent import agent_loop, insight_log

load_dotenv(override=True)
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")

MODEL = os.environ.get("MODEL_ID", "qwen/qwen-plus")
MCP_URL = os.environ.get("MCP_URL", "http://127.0.0.1:8000/mcp/sse")
LOG_DIR = os.environ.get("LOG_DIR", ".chatcfd")
AGENT_PORT = int(os.environ.get("AGENT_PORT", "8080"))

# --- Shared state (initialized on startup) ---
mcp_client: MCPClient = None
harness: Harness = None
pool: SessionPool = None

# --- FastAPI app ---
app = FastAPI(title="ChatCFD Agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    global mcp_client, harness, pool
    mcp_client = MCPClient(MCP_URL)
    mcp_client.load_tools()
    print(f"[Agent] Loaded {len(mcp_client._tools_raw)} MCP tools: {list(mcp_client._tool_names)}")
    harness = Harness()
    pool = SessionPool()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    session_id = f"ws_{id(ws)}"
    session = pool.get_or_create(session_id)
    print(f"[Agent] WebSocket connected: {session_id}")

    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
                query = data.get("content", raw)
            except json.JSONDecodeError:
                query = raw

            session.messages.append({"role": "user", "content": query})

            # Run agent loop (blocking — OK for Phase 1, async in Phase 2)
            result = agent_loop.run(session, mcp_client, harness, model=MODEL)

            # Send response to frontend
            await ws.send_json({
                "content": result.get("content", ""),
                "artifacts": result.get("artifacts", []),
            })

            insight_log.log_query(
                LOG_DIR, session_id, query,
                resolution="tool_resolved",
                tools_called=[],
            )
    except WebSocketDisconnect:
        print(f"[Agent] WebSocket disconnected: {session_id}")
        pool.destroy(session_id)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "tools": len(mcp_client._tools_raw) if mcp_client else 0,
        "model": MODEL,
    }


# --- CLI mode (fallback) ---
def cli():
    global mcp_client, harness, pool
    mcp_client = MCPClient(MCP_URL)
    mcp_client.load_tools()
    print(f"Loaded {len(mcp_client._tools_raw)} MCP tools: {list(mcp_client._tool_names)}")

    harness = Harness()
    pool = SessionPool()
    session = pool.get_or_create("cli")

    print("ChatCFD Agent CLI (type 'q' to quit)\n")
    while True:
        try:
            query = input("\033[36mchatcfd >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break

        session.messages.append({"role": "user", "content": query})
        result = agent_loop.run(session, mcp_client, harness, model=MODEL)
        if result.get("content"):
            print(result["content"])
        for art in result.get("artifacts", []):
            print(f"  [Artifact] {art.get('title', '')}: {art.get('summary', '')}")
        insight_log.log_query(LOG_DIR, "cli", query, resolution="tool_resolved")
        print()


if __name__ == "__main__":
    import sys
    if "--cli" in sys.argv:
        cli()
    else:
        print(f"[Agent] Starting WebSocket server on port {AGENT_PORT}")
        print(f"[Agent] Post service at {MCP_URL}")
        print(f"[Agent] LLM model: {MODEL}")
        uvicorn.run(app, host="0.0.0.0", port=AGENT_PORT)

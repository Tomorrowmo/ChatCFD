"""ChatCFD Agent Service — WebSocket server + CLI fallback."""

import asyncio
import json
import os
import sys

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from agent.mcp_client import MCPClient, MCPClientPool
from agent.harness import Harness
from agent.session import SessionPool
from agent import agent_loop, insight_log

load_dotenv(override=True)
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")

MODEL = os.environ.get("MODEL_ID", "qwen/qwen-plus")
MCP_URL = os.environ.get("MCP_URL", "http://127.0.0.1:8000/mcp/sse")
MEMPALACE_ENABLED = os.environ.get("MEMPALACE_ENABLED", "false").lower() == "true"
MEMPALACE_CMD = os.environ.get("MEMPALACE_CMD", "python")
MEMPALACE_ARGS = os.environ.get("MEMPALACE_ARGS", "-m mempalace.mcp_server")
LOG_DIR = os.environ.get("LOG_DIR", ".chatcfd")
AGENT_PORT = int(os.environ.get("AGENT_PORT", "8080"))

# --- Shared state (initialized before server starts) ---
mcp_pool = MCPClientPool()
harness = Harness(max_file_size_mb=int(os.environ.get("MAX_FILE_SIZE_MB", "0")))  # 0 = unlimited (local mode)
pool = SessionPool()

# --- FastAPI app ---
app = FastAPI(title="ChatCFD Agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    fallback_id = f"ws_{id(ws)}"
    print(f"[Agent] WebSocket connected (fallback={fallback_id})")

    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
                query = data.get("content", raw)
                conv_id = data.get("conversation_id") or fallback_id
            except json.JSONDecodeError:
                query = raw
                conv_id = fallback_id

            session = pool.get_or_create(conv_id)
            session.messages.append({"role": "user", "content": query})

            try:
                # Run sync generator in thread executor so WS can flush between tokens
                loop = asyncio.get_event_loop()
                gen = agent_loop.stream_run(
                    session, mcp_pool, harness, model=MODEL,
                    mcp_session_id=conv_id,
                )
                while True:
                    event = await loop.run_in_executor(None, lambda: next(gen, None))
                    if event is None:
                        break
                    await ws.send_json(event)
                    await asyncio.sleep(0)  # yield control to flush
            except Exception as e:
                await ws.send_json({
                    "type": "done",
                    "content": f"Error: {e}",
                    "artifacts": [],
                })

            insight_log.log_query(
                LOG_DIR, conv_id, query,
                resolution="tool_resolved",
                tools_called=[],
            )
    except WebSocketDisconnect:
        print(f"[Agent] WebSocket disconnected (fallback={fallback_id})")
        # M2-4: Auto-extract key conclusions at conversation end
        if MEMPALACE_ENABLED:
            _try_extract_memories(conv_id)


def _try_extract_memories(conv_id: str):
    """At conversation end, check if there are artifacts worth saving to memory."""
    session = pool.get(conv_id)
    if not session or not mcp_pool.has_tool("mempalace_add_drawer"):
        return
    # Collect summaries from tool results in conversation
    summaries = []
    for msg in session.messages:
        if msg.get("role") == "tool":
            try:
                data = json.loads(msg.get("content", "{}"))
                if isinstance(data, dict) and "summary" in data and "error" not in data:
                    summaries.append(data["summary"])
            except (json.JSONDecodeError, TypeError):
                pass
    if not summaries:
        return
    # Build a condensed summary of the conversation's key findings
    combined = "; ".join(summaries[:5])  # cap at 5 to avoid huge content
    wing = session.memory_wing or "default"
    try:
        from agent.agent_loop import _auto_dedup_drawer
        if not _auto_dedup_drawer(mcp_pool, combined):
            mcp_pool.call_tool("mempalace_add_drawer", {
                "wing": wing, "room": "results", "content": combined,
            })
            print(f"[Memory] Auto-saved session summary to wing={wing}")
    except Exception as e:
        print(f"[Memory] Auto-save failed: {e}")


@app.post("/api/settings")
async def update_settings(settings: dict):
    global MODEL
    if "model" in settings and settings["model"]:
        MODEL = settings["model"]
        print(f"[Agent] Model switched to: {MODEL}")
    if "api_base" in settings and settings["api_base"]:
        os.environ["OPENAI_API_BASE"] = settings["api_base"]
        os.environ["LLM_API_BASE"] = settings["api_base"]
        print(f"[Agent] API base updated")
    return {"status": "ok", "model": MODEL}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "tools": len(mcp_pool._tool_route),
        "model": MODEL,
    }


# --- CLI mode (fallback) ---
def _init_mcp_pool():
    """Register MCP servers and load all tools."""
    mcp_pool.add_client(MCPClient(
        name="post_service", transport="sse", url=MCP_URL,
    ))
    if MEMPALACE_ENABLED:
        mcp_pool.add_client(MCPClient(
            name="mempalace", transport="stdio",
            command=MEMPALACE_CMD, args=MEMPALACE_ARGS.split(),
        ))
    mcp_pool.load_all_tools()


def cli():
    _init_mcp_pool()
    tool_names = list(mcp_pool._tool_route.keys())
    print(f"Loaded {len(tool_names)} MCP tools: {tool_names}")

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
        result = agent_loop.run(session, mcp_pool, harness, model=MODEL)
        if result.get("content"):
            print(result["content"])
        for art in result.get("artifacts", []):
            print(f"  [Artifact] {art.get('title', '')}: {art.get('summary', '')}")
        insight_log.log_query(LOG_DIR, "cli", query, resolution="tool_resolved")
        print()


if __name__ == "__main__":
    if "--cli" in sys.argv:
        cli()
    else:
        # Load MCP tools BEFORE starting uvicorn
        _init_mcp_pool()
        llm_tools = mcp_pool.get_tools_for_llm()
        print(f"[Agent] {len(mcp_pool._tool_route)} total tools, {len(llm_tools)} exposed to LLM")
        print(f"[Agent] Starting WebSocket server on port {AGENT_PORT}")
        print(f"[Agent] Post service at {MCP_URL}")
        if MEMPALACE_ENABLED:
            print(f"[Agent] Mempalace enabled")
        print(f"[Agent] LLM model: {MODEL}")
        uvicorn.run(app, host="0.0.0.0", port=AGENT_PORT)

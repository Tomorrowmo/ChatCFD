"""ChatCFD Agent Service — WebSocket server + CLI fallback."""

import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager

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

MODEL = os.environ.get("MODEL_ID", "openai/qwen-plus")
MCP_URL = os.environ.get("MCP_URL", "http://127.0.0.1:8001/mcp/sse")
MEMPALACE_ENABLED = os.environ.get("MEMPALACE_ENABLED", "true").lower() == "true"
LOG_DIR = os.environ.get("LOG_DIR", ".chatcfd")
AGENT_PORT = int(os.environ.get("AGENT_PORT", "8080"))
SETTINGS_FILE = os.path.join(LOG_DIR, "settings.json")

# --- Shared state (initialized before server starts) ---
mcp_pool = MCPClientPool()
harness = Harness(max_file_size_mb=int(os.environ.get("MAX_FILE_SIZE_MB", "0")))  # 0 = unlimited (local mode)
pool = SessionPool()


def _apply_settings(s: dict):
    """Apply a settings dict (model/api_base/api_key) to env vars + MODEL global."""
    global MODEL
    if s.get("model"):
        MODEL = s["model"]
    if s.get("api_base"):
        os.environ["OPENAI_API_BASE"] = s["api_base"]
        os.environ["LLM_API_BASE"] = s["api_base"]
    if s.get("api_key"):
        os.environ["OPENAI_API_KEY"] = s["api_key"]
        os.environ["DASHSCOPE_API_KEY"] = s["api_key"]


def _load_persisted_settings():
    """Load previously-saved settings from disk, if present."""
    if not os.path.isfile(SETTINGS_FILE):
        return None
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        _apply_settings(data)
        return data
    except Exception as e:
        print(f"[Agent] Failed to load {SETTINGS_FILE}: {e}")
        return None


def _persist_settings(s: dict):
    """Write settings to disk so they survive restart. Merges with existing."""
    os.makedirs(LOG_DIR, exist_ok=True)
    existing = {}
    if os.path.isfile(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass
    merged = {**existing, **{k: v for k, v in s.items() if v}}
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)


# --- FastAPI lifespan: init MCP pool regardless of launch mode ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Only init once — reload / multiple workers would otherwise double-register
    if not mcp_pool._tool_route:
        loaded = _load_persisted_settings()
        _init_mcp_pool()
        llm_tools = mcp_pool.get_tools_for_llm()
        tool_names = list(mcp_pool._tool_route.keys())
        print(f"[Agent] {len(tool_names)} total tools, {len(llm_tools)} exposed to LLM")
        print(f"[Agent] Tools: {tool_names}")
        print(f"[Agent] Post service at {MCP_URL}")
        if MEMPALACE_ENABLED:
            print(f"[Agent] Mempalace enabled")
        print(f"[Agent] LLM model: {MODEL}")
        api_base = os.environ.get("OPENAI_API_BASE", "(unset — will default to OpenAI)")
        api_key_set = bool(os.environ.get("OPENAI_API_KEY"))
        print(f"[Agent] OPENAI_API_BASE: {api_base}")
        print(f"[Agent] OPENAI_API_KEY: {'(set)' if api_key_set else '(UNSET — LLM calls will fail)'}")
        if loaded:
            print(f"[Agent] Loaded persisted settings from {SETTINGS_FILE}")
        elif not api_key_set:
            print(f"[Agent] No persisted settings and no API key in env — open Web UI Settings to configure")
    yield


# --- FastAPI app ---
app = FastAPI(title="ChatCFD Agent", lifespan=lifespan)
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
    conv_id = fallback_id
    print(f"[Agent] WebSocket connected (fallback={fallback_id})")

    # Active generator task — can be cancelled
    active_task = None

    async def run_generator(session, conv_id, gen):
        """Stream generator events to WebSocket."""
        loop = asyncio.get_event_loop()
        try:
            while True:
                if getattr(session, 'cancelled', False):
                    gen.close()
                    await ws.send_json({"type": "done", "content": "已停止。", "artifacts": []})
                    return
                event = await loop.run_in_executor(None, lambda: next(gen, None))
                if event is None:
                    return
                await ws.send_json(event)
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            gen.close()
            await ws.send_json({"type": "done", "content": "已停止。", "artifacts": []})
        except Exception as e:
            await ws.send_json({"type": "done", "content": f"Error: {e}", "artifacts": []})

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

            # Handle cancel signal — cancel the active task
            if query == "__cancel__":
                session = pool.get(conv_id)
                if session:
                    session.cancelled = True
                if active_task and not active_task.done():
                    active_task.cancel()
                    active_task = None
                continue

            session = pool.get_or_create(conv_id)
            session.messages.append({"role": "user", "content": query})
            session.cancelled = False

            # Auto-detect coding confirmation.
            # Path A: user responds with a confirmation word to an assistant
            #         message that proposed coding.
            # Path B: user directly requests custom code/script execution in
            #         this turn (regardless of prior assistant message).
            if not session.user_confirmed_coding:
                q_lower = query.lower()

                _CONFIRM_KW = {"可以", "好的", "允许", "同意", "yes", "ok", "确认", "没问题", "行", "授权"}
                if any(kw in q_lower for kw in _CONFIRM_KW):
                    prev = [m for m in session.messages if m.get("role") == "assistant"]
                    if prev:
                        last = prev[-1].get("content", "") or ""
                        if any(k in last for k in ("编写", "脚本", "代码", "runBash", "runPython", "Python", "python")):
                            session.user_confirmed_coding = True

                if not session.user_confirmed_coding:
                    _CODING_NOUN = ("python", "脚本", "代码", "runbash", "runpython")
                    _CODING_VERB = ("用", "写", "执行", "跑", "运行", "调用")
                    if any(n in q_lower for n in _CODING_NOUN) and any(
                        v in query for v in _CODING_VERB
                    ):
                        session.user_confirmed_coding = True

            # Cancel previous task if still running.
            # Do NOT touch session.cancelled here — if the new query reuses the
            # same session (same conv_id), setting cancelled=True would make the
            # freshly-created generator exit immediately without calling the LLM.
            if active_task and not active_task.done():
                active_task.cancel()

            gen = agent_loop.stream_run(
                session, mcp_pool, harness, model=MODEL,
                mcp_session_id=conv_id,
            )
            active_task = asyncio.create_task(run_generator(session, conv_id, gen))

            # Wait for generator to finish, but keep reading WebSocket for cancel signals
            while not active_task.done():
                # Race: wait for either next WS message or task completion
                ws_receive = asyncio.ensure_future(ws.receive_text())
                done, pending = await asyncio.wait(
                    {ws_receive, active_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if ws_receive in done:
                    msg_raw = ws_receive.result()
                    try:
                        msg_data = json.loads(msg_raw)
                        msg_content = msg_data.get("content", "")
                    except json.JSONDecodeError:
                        msg_content = msg_raw
                    if msg_content == "__cancel__":
                        session.cancelled = True
                        active_task.cancel()
                        try:
                            await active_task
                        except asyncio.CancelledError:
                            pass
                        break
                else:
                    ws_receive.cancel()

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
    _apply_settings(settings)
    _persist_settings(settings)
    if settings.get("model"):
        print(f"[Agent] Model switched to: {MODEL}")
    if settings.get("api_base"):
        print(f"[Agent] API base updated")
    if settings.get("api_key"):
        print(f"[Agent] API key updated")
    print(f"[Agent] Settings persisted to {SETTINGS_FILE}")
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
            command=sys.executable, args=["-m", "mempalace.mcp_server"],
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
        # lifespan hook handles _init_mcp_pool() + startup banner
        print(f"[Agent] Starting WebSocket server on port {AGENT_PORT}")
        uvicorn.run(app, host="0.0.0.0", port=AGENT_PORT)

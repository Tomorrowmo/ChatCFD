"""ChatCFD Agent — CLI mode for Phase 1 testing."""

import os

from dotenv import load_dotenv

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


def main():
    mcp = MCPClient(MCP_URL)
    mcp.load_tools()
    print(f"Loaded {len(mcp._tools_raw)} MCP tools: {list(mcp._tool_names)}")

    harness = Harness()
    pool = SessionPool()
    session = pool.get_or_create("cli")

    print("ChatCFD Agent (type 'q' to quit)\n")
    while True:
        try:
            query = input("\033[36mchatcfd >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break

        session.messages.append({"role": "user", "content": query})
        reply = agent_loop.run(session, mcp, harness, model=MODEL)
        if reply:
            print(reply)
        insight_log.log_query(LOG_DIR, "cli", query, resolution="tool_resolved")
        print()


if __name__ == "__main__":
    main()

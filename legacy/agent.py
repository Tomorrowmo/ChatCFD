#!/usr/bin/env python3
"""
SimGraph Agent - Step 1: The Agent Loop (s01)

The simplest possible agent: one loop, one tool (bash).

    +----------+      +-------+      +---------+
    |   User   | ---> |  LLM  | ---> |  Tool   |
    |  prompt  |      | Qwen  |      | execute |
    +----------+      +---+---+      +----+----+
                          ^               |
                          |   tool_result  |
                          +---------------+
"""

import os
import subprocess
from pathlib import Path

from openai import OpenAI
from dotenv import load_dotenv
import asyncio # 2024-06-17: Qwen SDK 现在支持异步了！未来可以改成 async/await 来提升性能。
import json as json_module # 避免和工具函数中的 json 冲突
from mcp.client.sse import sse_client # 2024-06-17: MCP 的 Server-Sent Events 客户端，用于接收流式工具结果。
from mcp import ClientSession # 2024-06-17: MCP 的客户端会话，用于管理工具调用的上下文和状态。

load_dotenv(override=True) # 读取 .env 文件中的环境变量，覆盖系统环境变量

# 本地 MCP Server 连接绕过代理
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")

# -- Configuration --
WORKDIR = Path.cwd()# 工作目录，工具执行的上下文
client = OpenAI(
    api_key=os.environ["DASHSCOPE_API_KEY"],# 从环境变量读取 API Key
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)
MODEL = os.environ.get("MODEL_ID", "qwen-plus") # 模型 ID，默认为 "qwen-plus"

# -- System prompt: SimGraph's identity --
SYSTEM = f"""你是 SimGraph 的智能助手，工作目录是 {WORKDIR}。
SimGraph 是航空航天 CFD 仿真数据智能管理平台。
你的职责是帮助仿真工程师管理、查询和分析 CFD 仿真数据。
用工具解决问题，不要只解释。
重要：只使用系统提供给你的工具，不要编造不存在的工具或功能。如果用户问你有哪些工具，只列出你实际可用的工具。"""

# -- Tools: just bash for now (s01 level) --
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run a shell command.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The command to run"}
                },
                "required": ["command"],
            },
        },
    }
]# 工具定义：一个名为 "bash" 的函数工具，接受一个字符串参数 "command"。

#--MCP Client -- 2024-06-17: 初始化 MCP 客户端会话，用于后续工具调用的上下文管理。
MCP_URL = "http://127.0.0.1:8000/sse" # MCP 服务地址，假设本地运行在 8000 端口
MCP_TOOLS = [] # 这里可以添加 MCP 工具的定义，格式类似于 TOOLS 中的函数定义
MCP_TOOL_NAMES = set()  # 用于快速检查工具名称，避免重复
MCP_TOOLS_RAW = []  # MCP 原始格式（通用）
def load_mcp_tools():
    '''启动时连接MCP Server，获取工具列表，转成千问格式'''
    async def _load():
        async with sse_client(MCP_URL) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                for tool in tools.tools:
                    MCP_TOOL_NAMES.add(tool.name)
                    MCP_TOOLS_RAW.append({
                        "name": tool.name,
                        "description": tool.description or "",
                        "inputSchema": tool.inputSchema or {},
                    })
    try:
        asyncio.run(_load())
        print(f"Loaded {len(MCP_TOOLS_RAW)} MCP tools: {list(MCP_TOOL_NAMES)}")
    except Exception as e:
        print(f"[MCP Warning] Could not connect: {e}")

def mcp_tools_for_qwen(raw_tools: list) -> list:
    """MCP 原始格式 → 千问格式"""
    return [{
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["inputSchema"],
        },
    } for t in raw_tools]

def call_mcp_tool(name: str, arguments: dict) -> str:
    """调用 MCP Server 上的工具。"""
    async def _call():
        async with sse_client(MCP_URL) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments)
                return str(result.content[0].text) if result.content else "(no result)"
    try:
        return asyncio.run(_call())
    except Exception as e:
        return f"MCP Error: {e}"

def run_bash(command: str) -> str:# 运行
    """Execute a shell command and return output."""
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(
            command, shell=True, cwd=WORKDIR,
            capture_output=True, text=True, timeout=120,
        )
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"


def agent_loop(messages: list):
    """The core loop: ask model, execute tools, feed results back."""
    while True:
        # Ask the model
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": SYSTEM}] + messages,
                tools=TOOLS + mcp_tools_for_qwen(MCP_TOOLS_RAW),
                max_tokens=8000,
            )
        except Exception as e:
            print(f"\n[API Error] {type(e).__name__}: {e}")
            # 移除刚加入的用户消息，避免污染历史
            if messages and messages[-1].get("role") == "user":
                messages.pop()
            return
        msg = response.choices[0].message

        # Append assistant message
        messages.append(msg.model_dump())

        # If no tool calls, we're done
        if not msg.tool_calls:
            return

        # Execute each tool call
        for tool_call in msg.tool_calls:
            name = tool_call.function.name
            args = eval(tool_call.function.arguments)  # Qwen returns JSON string

            if name == "bash":
                output = run_bash(args["command"])
            elif name in MCP_TOOL_NAMES:
                output = call_mcp_tool(name, args)
            else:
                output = f"Unknown tool: {name}"

            print(f"> {name}: {str(output)[:200]}")

            # Feed result back
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": str(output),
            })


if __name__ == "__main__":
    print(f"SimGraph Agent at {WORKDIR}")
    print("Type 'q' to quit.\n")
    load_mcp_tools() # 启动时加载 MCP 工具列表

    history = []
    while True:
        try:
            query = input("\033[36msimgraph >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break

        history.append({"role": "user", "content": query})
        agent_loop(history)

        # Print assistant's text response
        last = history[-1]
        if isinstance(last, dict) and last.get("role") == "assistant":
            content = last.get("content")
            if content:
                print(content)
        elif hasattr(last, "content") and last.content:
            print(last.content)
        print()

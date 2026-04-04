"""AgentLoop — LLM -> tool_call -> Harness -> MCP dispatch -> repeat."""

import json

import litellm

from agent.harness import Harness
from agent.mcp_client import MCPClient
from agent.session import AgentSession
from agent.skills import build_system_prompt


def run(session: AgentSession, mcp_client: MCPClient, harness: Harness,
        model: str = "qwen/qwen-plus", max_rounds: int = 10) -> dict:
    """Execute the agent loop: LLM reasoning with tool dispatch.

    Returns {"content": str, "artifacts": list[dict]} where artifacts are
    tool results that have type/summary/data fields (for frontend display).
    """
    system_msg = {"role": "system", "content": build_system_prompt()}
    tools = mcp_client.get_tools_for_llm()
    artifacts = []

    for _ in range(max_rounds):
        response = litellm.completion(
            model=model,
            messages=[system_msg] + session.messages,
            tools=tools if tools else None,
            max_tokens=4096,
        )
        msg = response.choices[0].message
        session.messages.append(msg.model_dump(exclude_none=True))

        # No tool calls => final answer
        if not msg.tool_calls:
            return {"content": msg.content or "", "artifacts": artifacts}

        # Process each tool call
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            # Harness before-check
            blocked = harness.before_call(
                name, args,
                user_confirmed_coding=session.user_confirmed_coding,
            )
            if blocked:
                result = json.dumps(blocked, ensure_ascii=False)
            elif mcp_client.has_tool(name):
                raw = mcp_client.call_tool(name, args)
                try:
                    parsed = json.loads(raw)
                    parsed = harness.after_call(name, parsed)
                    result = json.dumps(parsed, ensure_ascii=False)
                    # Collect artifacts from tool results
                    if isinstance(parsed, dict) and "summary" in parsed:
                        artifacts.append({
                            "title": f"{name} result",
                            "type": parsed.get("type", "numerical"),
                            "summary": parsed.get("summary", ""),
                            "data": parsed.get("data"),
                            "output_files": parsed.get("output_files", []),
                        })
                except json.JSONDecodeError:
                    result = raw
            else:
                result = json.dumps({"error": f"Unknown tool: {name}"})

            session.messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    return {"content": "Maximum rounds reached.", "artifacts": artifacts}


def stream_run(session: AgentSession, mcp_client: MCPClient, harness: Harness,
               model: str = "qwen/qwen-plus", max_rounds: int = 10):
    """Generator version of run(). Yields dicts for WebSocket streaming.

    Yields:
        {"type": "token", "content": "partial text"}       — LLM text token
        {"type": "tool_start", "tool": "loadFile", ...}    — tool call begins
        {"type": "tool_result", "tool": "loadFile", ...}   — tool call finished
        {"type": "done", "content": "full text", "artifacts": [...]}  — final
    """
    system_msg = {"role": "system", "content": build_system_prompt()}
    tools = mcp_client.get_tools_for_llm()
    artifacts = []

    for _ in range(max_rounds):
        # Streaming LLM call
        response = litellm.completion(
            model=model,
            messages=[system_msg] + session.messages,
            tools=tools if tools else None,
            max_tokens=4096,
            stream=True,
        )

        # Accumulate streamed response
        full_content = ""
        tool_calls_acc = {}  # {index: {id, name, arguments_str}}

        for chunk in response:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            # Text content streaming
            if delta.content:
                full_content += delta.content
                yield {"type": "token", "content": delta.content}

            # Tool call streaming (accumulated across chunks)
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {
                            "id": tc_delta.id or "",
                            "name": tc_delta.function.name if tc_delta.function and tc_delta.function.name else "",
                            "arguments": tc_delta.function.arguments if tc_delta.function and tc_delta.function.arguments else "",
                        }
                    else:
                        if tc_delta.id:
                            tool_calls_acc[idx]["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                tool_calls_acc[idx]["name"] += tc_delta.function.name
                            if tc_delta.function.arguments:
                                tool_calls_acc[idx]["arguments"] += tc_delta.function.arguments

        # Build assistant message for history
        assistant_msg = {"role": "assistant", "content": full_content or None}
        if tool_calls_acc:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for tc in tool_calls_acc.values()
            ]
        session.messages.append(assistant_msg)

        # No tool calls => done
        if not tool_calls_acc:
            yield {"type": "done", "content": full_content, "artifacts": artifacts}
            return

        # Execute tool calls
        for tc in tool_calls_acc.values():
            name = tc["name"]
            try:
                args = json.loads(tc["arguments"])
            except json.JSONDecodeError:
                args = {}

            yield {"type": "tool_start", "tool": name, "args": args}

            blocked = harness.before_call(
                name, args,
                user_confirmed_coding=session.user_confirmed_coding,
            )
            if blocked:
                result = json.dumps(blocked, ensure_ascii=False)
            elif mcp_client.has_tool(name):
                raw = mcp_client.call_tool(name, args)
                try:
                    parsed = json.loads(raw)
                    parsed = harness.after_call(name, parsed)
                    result = json.dumps(parsed, ensure_ascii=False)
                    if isinstance(parsed, dict) and "summary" in parsed:
                        artifact = {
                            "title": f"{name} result",
                            "type": parsed.get("type", "numerical"),
                            "summary": parsed.get("summary", ""),
                            "data": parsed.get("data"),
                            "output_files": parsed.get("output_files", []),
                        }
                        artifacts.append(artifact)
                except json.JSONDecodeError:
                    result = raw
            else:
                result = json.dumps({"error": f"Unknown tool: {name}"})

            session.messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })

            yield {"type": "tool_result", "tool": name, "summary": parsed.get("summary", "") if "parsed" in dir() else ""}

    yield {"type": "done", "content": "Maximum rounds reached.", "artifacts": artifacts}

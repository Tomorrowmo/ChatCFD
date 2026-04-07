"""AgentLoop — LLM -> tool_call -> Harness -> MCP dispatch -> repeat."""

import json

import litellm

from agent.harness import Harness
from agent.mcp_client import MCPClient
from agent.session import AgentSession
from agent.skills import build_system_prompt


def _make_artifact_title(tool_name: str, args: dict, result: dict) -> str:
    """Generate a descriptive artifact title from tool name + args."""
    if tool_name == "calculate":
        method = args.get("method", "")
        zone = args.get("zone_name", "")
        # Method-specific titles
        titles = {
            "statistics": f"Statistics: {zone}" if zone else "Statistics",
            "force_moment": f"Force & Moment: {zone}" if zone else "Force & Moment",
            "velocity_gradient": "Velocity Gradient (Vorticity/Mach)",
            "slice": f"Slice: {zone}" if zone else "Slice",
            "streamline": f"Streamlines: {zone}" if zone else "Streamlines",
            "contour": f"Contour: {zone}" if zone else "Contour",
            "render": f"Render: {zone}" if zone else "Render",
            "compare": "Compare",
        }
        return titles.get(method, f"{method}: {zone}" if zone else method)
    if tool_name == "exportData":
        zone = args.get("zone", "")
        fmt = args.get("format", "csv")
        return f"Export: {zone}.{fmt}" if zone else f"Export ({fmt})"
    if tool_name == "listFiles":
        return "File List"
    if tool_name == "getMethodTemplate":
        return f"Methods: {args.get('method', 'all')}"
    return f"{tool_name}"


def run(session: AgentSession, mcp_client: MCPClient, harness: Harness,
        model: str = "qwen/qwen-plus", max_rounds: int = 10,
        mcp_session_id: str = "default") -> dict:
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

            # Transparently inject session_id so the LLM doesn't manage it
            args["session_id"] = mcp_session_id

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
                    if isinstance(parsed, dict) and "error" not in parsed:
                        if name == "loadFile":
                            artifacts.append({
                                "title": f"loadFile: {parsed.get('file_path', 'unknown').split('/')[-1]}",
                                "type": "numerical",
                                "summary": f"{parsed.get('zone_count', 0)} zones, {parsed.get('total_cells', 0)} cells, {parsed.get('total_points', 0)} points",
                                "data": parsed,
                                "output_files": [],
                            })
                        elif "summary" in parsed:
                            artifacts.append({
                                "title": _make_artifact_title(name, args, parsed),
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
               model: str = "qwen/qwen-plus", max_rounds: int = 10,
               mcp_session_id: str = "default"):
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

            # Transparently inject session_id so the LLM doesn't manage it
            args["session_id"] = mcp_session_id

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
                    if isinstance(parsed, dict) and "error" not in parsed:
                        # loadFile returns {file_path, zones, ...} directly (not in "data")
                        # calculate/export return unified {type, summary, data, output_files}
                        if name == "loadFile":
                            artifact = {
                                "title": f"loadFile: {parsed.get('file_path', 'unknown').split('/')[-1]}",
                                "type": "numerical",
                                "summary": f"{parsed.get('zone_count', 0)} zones, {parsed.get('total_cells', 0)} cells, {parsed.get('total_points', 0)} points",
                                "data": parsed,
                                "output_files": [],
                            }
                            artifacts.append(artifact)
                        elif "summary" in parsed:
                            artifact = {
                                "title": _make_artifact_title(name, args, parsed),
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

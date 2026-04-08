"""AgentLoop — LLM -> tool_call -> Harness -> MCP dispatch -> repeat."""

import json

import litellm

from agent.harness import Harness
from agent.mcp_client import MCPClientPool
from agent.session import AgentSession
from agent.skills import build_system_prompt


def _make_artifact_title(tool_name: str, args: dict, result: dict) -> str:
    """Generate a user-friendly artifact title from tool call context."""
    if tool_name == "calculate":
        method = args.get("method", "")
        params = args.get("params", {})
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except (json.JSONDecodeError, TypeError):
                params = {}
        data = result.get("data", {}) if isinstance(result, dict) else {}

        if method == "slice":
            normal = params.get("normal", [])
            axis = {str([1,0,0]): "X", str([0,1,0]): "Y", str([0,0,1]): "Z"}.get(str(normal), "")
            return f"Slice {axis}" if axis else "Slice"
        if method == "clip":
            return "Clip"
        if method == "contour":
            scalar = params.get("scalar", "")
            value = params.get("value", "")
            if scalar and value:
                return f"Contour: {scalar}={value}"
            return f"Contour: {scalar}" if scalar else "Contour"
        if method == "streamline":
            return "Streamlines"
        if method == "render":
            scalar = params.get("scalar", "")
            return f"Render: {scalar}" if scalar else "Render"
        if method == "statistics":
            zone = args.get("zone_name", "")
            return f"Statistics: {zone}" if zone else "Statistics"
        if method == "force_moment":
            zone = args.get("zone_name", "")
            return f"Force & Moment: {zone}" if zone else "Force & Moment"
        if method == "velocity_gradient":
            return "Vorticity / Mach"
        if method == "compare":
            return "Compare"
        return method

    if tool_name == "exportData":
        zone = args.get("zone", "")
        return f"Export: {zone}" if zone else "Export"
    if tool_name == "listFiles":
        return "File List"
    if tool_name == "getMethodTemplate":
        return f"Methods: {args.get('method', 'all')}"
    return tool_name


def _infer_wing(file_path: str) -> str:
    """Infer mempalace wing name from file path (parent directory name)."""
    import os
    path = file_path.replace("\\", "/")
    parent = os.path.basename(os.path.dirname(path))
    return parent.lower().replace(" ", "_").replace("-", "_") if parent else "default"


def _inject_memory_after_load(session: AgentSession, mcp_pool: MCPClientPool,
                              file_path: str):
    """After loadFile, infer wing and search for relevant memories."""
    if not mcp_pool.has_tool("mempalace_search"):
        return
    wing = _infer_wing(file_path)
    session.memory_wing = wing
    session.loaded_file_path = file_path
    try:
        raw = mcp_pool.call_tool("mempalace_search", {
            "query": f"analysis of {file_path.split('/')[-1]}",
            "wing": wing, "limit": 3,
        })
        result = json.loads(raw)
        memories = result.get("results", [])
        if memories:
            texts = [m.get("text", "") for m in memories[:3]]
            hint = "## 相关历史记忆\n" + "\n".join(f"- {t}" for t in texts)
            session.messages.append({"role": "system", "content": hint})
    except Exception as e:
        print(f"[Memory] search failed: {e}")


def _inject_global_preferences(session: AgentSession, mcp_pool: MCPClientPool):
    """At conversation start, inject user preferences from knowledge graph."""
    if not mcp_pool.has_tool("mempalace_kg_query"):
        return
    try:
        raw = mcp_pool.call_tool("mempalace_kg_query", {
            "entity": "user", "direction": "outgoing",
        })
        result = json.loads(raw)
        facts = result.get("facts", [])
        current = [f for f in facts if f.get("current", True)]
        if current:
            lines = [f"{f['predicate']}: {f['object']}" for f in current]
            hint = "## 用户偏好\n" + "\n".join(f"- {l}" for l in lines)
            session.messages.insert(0, {"role": "system", "content": hint})
    except Exception as e:
        print(f"[Memory] kg_query failed: {e}")


def _auto_dedup_drawer(mcp_pool: MCPClientPool, content: str) -> bool:
    """Check duplicate before add_drawer. Returns True if duplicate found."""
    if not mcp_pool.has_tool("mempalace_check_duplicate"):
        return False
    try:
        raw = mcp_pool.call_tool("mempalace_check_duplicate", {
            "content": content, "threshold": 0.9,
        })
        result = json.loads(raw)
        return result.get("is_duplicate", False)
    except Exception:
        return False


def run(session: AgentSession, mcp_pool: MCPClientPool, harness: Harness,
        model: str = "qwen/qwen-plus", max_rounds: int = 10,
        mcp_session_id: str = "default") -> dict:
    """Execute the agent loop: LLM reasoning with tool dispatch.

    Returns {"content": str, "artifacts": list[dict]} where artifacts are
    tool results that have type/summary/data fields (for frontend display).
    """
    # Inject global user preferences at conversation start
    if len(session.messages) <= 1:
        _inject_global_preferences(session, mcp_pool)

    system_msg = {"role": "system", "content": build_system_prompt()}
    tools = mcp_pool.get_tools_for_llm()
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
            if name.startswith("mempalace_"):
                pass  # mempalace tools don't use session_id
            else:
                args["session_id"] = mcp_session_id

            # Auto-dedup before add_drawer
            if name == "mempalace_add_drawer":
                content = args.get("content", "")
                if content and _auto_dedup_drawer(mcp_pool, content):
                    result = json.dumps({"info": "Duplicate content, skipped."})
                    session.messages.append({
                        "role": "tool", "tool_call_id": tc.id, "content": result,
                    })
                    continue

            # Harness before-check
            blocked = harness.before_call(
                name, args,
                user_confirmed_coding=session.user_confirmed_coding,
            )
            if blocked:
                result = json.dumps(blocked, ensure_ascii=False)
            elif mcp_pool.has_tool(name):
                raw = mcp_pool.call_tool(name, args)
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
                            # Memory: inject related memories after loadFile
                            file_path = args.get("file_path", "")
                            if file_path:
                                _inject_memory_after_load(session, mcp_pool, file_path)
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


def stream_run(session: AgentSession, mcp_pool: MCPClientPool, harness: Harness,
               model: str = "qwen/qwen-plus", max_rounds: int = 10,
               mcp_session_id: str = "default"):
    """Generator version of run(). Yields dicts for WebSocket streaming.

    Yields:
        {"type": "token", "content": "partial text"}       — LLM text token
        {"type": "tool_start", "tool": "loadFile", ...}    — tool call begins
        {"type": "tool_result", "tool": "loadFile", ...}   — tool call finished
        {"type": "done", "content": "full text", "artifacts": [...]}  — final
    """
    # Inject global user preferences at conversation start
    if len(session.messages) <= 1:
        _inject_global_preferences(session, mcp_pool)

    system_msg = {"role": "system", "content": build_system_prompt()}
    tools = mcp_pool.get_tools_for_llm()
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

            # Transparently inject session_id (mempalace tools don't use it)
            if name.startswith("mempalace_"):
                pass
            else:
                args["session_id"] = mcp_session_id

            # Auto-dedup before add_drawer
            if name == "mempalace_add_drawer":
                content = args.get("content", "")
                if content and _auto_dedup_drawer(mcp_pool, content):
                    session.messages.append({
                        "role": "tool", "tool_call_id": tc["id"],
                        "content": json.dumps({"info": "Duplicate content, skipped."}),
                    })
                    yield {"type": "tool_result", "tool": name, "summary": "duplicate, skipped"}
                    continue

            yield {"type": "tool_start", "tool": name, "args": args}

            blocked = harness.before_call(
                name, args,
                user_confirmed_coding=session.user_confirmed_coding,
            )
            if blocked:
                result = json.dumps(blocked, ensure_ascii=False)
            elif mcp_pool.has_tool(name):
                raw = mcp_pool.call_tool(name, args)
                try:
                    parsed = json.loads(raw)
                    parsed = harness.after_call(name, parsed)
                    result = json.dumps(parsed, ensure_ascii=False)
                    if isinstance(parsed, dict) and "error" not in parsed:
                        if name == "loadFile":
                            artifact = {
                                "title": f"loadFile: {parsed.get('file_path', 'unknown').split('/')[-1]}",
                                "type": "numerical",
                                "summary": f"{parsed.get('zone_count', 0)} zones, {parsed.get('total_cells', 0)} cells, {parsed.get('total_points', 0)} points",
                                "data": parsed,
                                "output_files": [],
                            }
                            artifacts.append(artifact)
                            # Memory: inject related memories after loadFile
                            file_path = args.get("file_path", "")
                            if file_path:
                                _inject_memory_after_load(session, mcp_pool, file_path)
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

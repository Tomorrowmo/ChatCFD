"""AgentLoop — LLM -> tool_call -> Harness -> MCP dispatch -> repeat."""

import json
import time

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
            direction = params.get("direction", 0)
            axis = {0: "X", 1: "Y", 2: "Z"}.get(int(direction), "")
            n_slices = params.get("n_slices", "")
            if axis:
                return f"Slice {axis} x{n_slices}" if n_slices else f"Slice {axis}"
            return "Slice"
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
        if method == "vector_field":
            return "Vector Field"
        if method == "volume_render":
            scalar = params.get("scalar", "")
            return f"Volume Render: {scalar}" if scalar else "Volume Render"
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
    """Infer mempalace wing name from file path.

    Strategy: walk up from file, skip generic directory names, use the first
    meaningful project-level directory as wing name.
    """
    import os
    path = file_path.replace("\\", "/").rstrip("/")
    parts = [p for p in path.split("/") if p]

    # Skip the filename itself, walk up directories
    skip = {"data", "cgns", "plt", "vtm", "case", "results", "output", "cases", "runs"}
    for part in reversed(parts[:-1]):
        name = part.lower().replace(" ", "_").replace("-", "_")
        if name and name not in skip and not name.startswith(".") and len(name) > 1:
            return name
    return "default"


def _inject_memory_after_load(session: AgentSession, mcp_pool: MCPClientPool,
                              file_path: str):
    """After loadFile, infer wing (or use user override) and search for memories."""
    if not mcp_pool.has_tool("mempalace_search"):
        return
    # Use user-overridden wing if set, otherwise infer from path
    wing = session.memory_wing or _infer_wing(file_path)
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
        print("[Memory] kg_query tool not available, skipping preferences")
        return
    try:
        raw = mcp_pool.call_tool("mempalace_kg_query", {
            "entity": "user", "direction": "outgoing",
        })
        print(f"[Memory] kg_query raw response: {raw[:200]}")
        result = json.loads(raw)
        facts = result.get("facts", [])
        current = [f for f in facts if f.get("current", True)]
        if current:
            lines = [f"{f['predicate']}: {f['object']}" for f in current]
            hint = "## 用户偏好\n" + "\n".join(f"- {l}" for l in lines)
            session.messages.insert(0, {"role": "system", "content": hint})
            print(f"[Memory] Injected {len(current)} preferences")
        else:
            print("[Memory] No user preferences found")
    except Exception as e:
        print(f"[Memory] kg_query failed: {e}")


def _auto_invalidate_old_preference(mcp_pool: MCPClientPool,
                                    subject: str, predicate: str):
    """Before kg_add, invalidate any existing fact with same subject+predicate."""
    if not mcp_pool.has_tool("mempalace_kg_invalidate"):
        return
    try:
        mcp_pool.call_tool("mempalace_kg_invalidate", {
            "subject": subject, "predicate": predicate, "object": "",
        })
    except Exception:
        pass  # best-effort: if old fact doesn't exist, invalidate is a no-op


def _tool_call_signature(name: str, args: dict) -> str:
    """Stable signature for a tool call, ignoring injected `session_id`.

    Two calls that differ only in session_id are considered identical for
    the purpose of duplicate-call detection.
    """
    payload = {k: v for k, v in args.items() if k != "session_id"}
    return name + "::" + json.dumps(payload, sort_keys=True, ensure_ascii=False)


_DUPLICATE_CALL_HINT = (
    "Duplicate call rejected: the previous call to this tool with identical "
    "arguments just ran — its result is above in the scrollback. Either accept "
    "that result, or change parameters meaningfully. If the tool cannot do "
    "what you intend, call getMethodTemplate(method='{name}') to inspect its "
    "real parameters instead of guessing."
)


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
    tools = mcp_pool.get_tools_for_llm(
        include_coding=session.user_confirmed_coding,
    )
    artifacts = []
    last_tool_sig: str | None = None  # harness-level duplicate-call guard

    for _ in range(max_rounds):
        try:
            response = litellm.completion(
                model=model,
                messages=[system_msg] + session.messages,
                tools=tools if tools else None,
                max_tokens=4096,
            )
        except Exception as e:
            err_msg = str(e).lower()
            if "quota" in err_msg or "balance" in err_msg or "insufficient" in err_msg or "rate" in err_msg:
                return {"content": "API 额度不足或已用完，请在设置中更换 API Key 或切换模型。", "artifacts": artifacts}
            return {"content": f"LLM 调用失败: {e}", "artifacts": artifacts}
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
                # Auto-fill wing from session if not specified by LLM
                if not args.get("wing") and session.memory_wing:
                    args["wing"] = session.memory_wing
                content = args.get("content", "")
                if content and _auto_dedup_drawer(mcp_pool, content):
                    result = json.dumps({"info": "Duplicate content, skipped."})
                    session.messages.append({
                        "role": "tool", "tool_call_id": tc.id, "content": result,
                    })
                    continue

            # Auto-invalidate old preference before kg_add
            if name == "mempalace_kg_add":
                _auto_invalidate_old_preference(
                    mcp_pool, args.get("subject", ""), args.get("predicate", ""),
                )

            # Duplicate-call guard (harness level, independent of prompt):
            # reject back-to-back identical tool invocations so a confused LLM
            # cannot burn resources repeating the same call 10 times.
            sig = _tool_call_signature(name, args)
            if sig == last_tool_sig:
                result = json.dumps(
                    {"error": _DUPLICATE_CALL_HINT.format(name=name)},
                    ensure_ascii=False,
                )
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
                    full = json.loads(raw)
                    # Artifact uses the full parsed result (frontend can handle it).
                    # LLM only sees after_call (may truncate oversized `data`).
                    truncated = harness.after_call(name, full)
                    result = json.dumps(truncated, ensure_ascii=False)
                    if isinstance(full, dict) and "error" not in full:
                        if name == "loadFile":
                            source_file = full.get("file_path", "")
                            session.loaded_file_path = source_file
                            artifacts.append({
                                "title": f"loadFile: {source_file.split('/')[-1]}",
                                "type": "numerical",
                                "summary": f"{full.get('zone_count', 0)} zones, {full.get('total_cells', 0)} cells, {full.get('total_points', 0)} points",
                                "data": full,
                                "output_files": [],
                                "source_file": source_file,
                            })
                            # Memory: inject related memories after loadFile
                            if source_file:
                                _inject_memory_after_load(session, mcp_pool, source_file)
                        elif "summary" in full:
                            artifacts.append({
                                "title": _make_artifact_title(name, args, full),
                                "type": full.get("type", "numerical"),
                                "summary": full.get("summary", ""),
                                "data": full.get("data"),
                                "output_files": full.get("output_files", []),
                                "source_file": getattr(session, 'loaded_file_path', ''),
                            })
                except json.JSONDecodeError:
                    result = raw
            else:
                result = json.dumps({"error": f"Unknown tool: {name}"})

            # Only record signature for *actually executed* calls. Blocked
            # or unknown-tool responses stay off the record so a retry after
            # correction isn't itself flagged as a duplicate.
            last_tool_sig = sig
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
    tools = mcp_pool.get_tools_for_llm(
        include_coding=session.user_confirmed_coding,
    )
    artifacts = []
    last_tool_sig: str | None = None  # harness-level duplicate-call guard

    for round_i in range(max_rounds):
        # Streaming LLM call
        t_llm_start = time.perf_counter()
        try:
            response = litellm.completion(
                model=model,
                messages=[system_msg] + session.messages,
                tools=tools if tools else None,
                max_tokens=4096,
                stream=True,
            )
        except Exception as e:
            err_msg = str(e).lower()
            if "quota" in err_msg or "balance" in err_msg or "insufficient" in err_msg or "rate" in err_msg:
                yield {"type": "done", "content": "API 额度不足或已用完，请在设置中更换 API Key 或切换模型。", "artifacts": artifacts}
            else:
                yield {"type": "done", "content": f"LLM 调用失败: {e}", "artifacts": artifacts}
            return

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
                        # First chunk of a new tool call — notify frontend immediately
                        tool_name_hint = (tc_delta.function.name or "") if tc_delta.function else ""
                        if tool_name_hint:
                            yield {"type": "tool_pending", "tool": tool_name_hint}
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

        t_llm_end = time.perf_counter()
        print(f"[Timing] LLM round {round_i} stream: {t_llm_end - t_llm_start:.2f}s")

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
                if not args.get("wing") and session.memory_wing:
                    args["wing"] = session.memory_wing
                content = args.get("content", "")
                if content and _auto_dedup_drawer(mcp_pool, content):
                    session.messages.append({
                        "role": "tool", "tool_call_id": tc["id"],
                        "content": json.dumps({"info": "Duplicate content, skipped."}),
                    })
                    yield {"type": "tool_result", "tool": name, "summary": "duplicate, skipped"}
                    continue

            # Auto-invalidate old preference before kg_add
            if name == "mempalace_kg_add":
                _auto_invalidate_old_preference(
                    mcp_pool, args.get("subject", ""), args.get("predicate", ""),
                )

            # Duplicate-call guard (harness level, independent of prompt):
            # reject back-to-back identical tool invocations so a confused LLM
            # cannot burn resources repeating the same call 10 times.
            sig = _tool_call_signature(name, args)
            if sig == last_tool_sig:
                result = json.dumps(
                    {"error": _DUPLICATE_CALL_HINT.format(name=name)},
                    ensure_ascii=False,
                )
                session.messages.append({
                    "role": "tool", "tool_call_id": tc["id"], "content": result,
                })
                yield {"type": "tool_result", "tool": name,
                       "summary": "duplicate call rejected"}
                continue

            yield {"type": "tool_start", "tool": name, "args": args}

            t0 = time.perf_counter()
            blocked = harness.before_call(
                name, args,
                user_confirmed_coding=session.user_confirmed_coding,
            )
            if blocked:
                result = json.dumps(blocked, ensure_ascii=False)
            elif mcp_pool.has_tool(name):
                t1 = time.perf_counter()
                raw = mcp_pool.call_tool(name, args)
                t2 = time.perf_counter()
                print(f"[Timing] mcp_pool.call_tool({name}): {t2 - t1:.2f}s")
                try:
                    full = json.loads(raw)
                    truncated = harness.after_call(name, full)
                    result = json.dumps(truncated, ensure_ascii=False)
                    if isinstance(full, dict) and "error" not in full:
                        if name == "loadFile":
                            source_file = full.get("file_path", "")
                            session.loaded_file_path = source_file
                            artifact = {
                                "title": f"loadFile: {source_file.split('/')[-1]}",
                                "type": "numerical",
                                "summary": f"{full.get('zone_count', 0)} zones, {full.get('total_cells', 0)} cells, {full.get('total_points', 0)} points",
                                "data": full,
                                "output_files": [],
                                "source_file": source_file,
                            }
                            artifacts.append(artifact)
                            # Memory injection disabled at loadFile time to avoid
                            # 3-10s subprocess overhead. LLM can still call
                            # mempalace_search manually when user asks.
                        elif name in ("runBash", "runPython") and full.get("output_files"):
                            for fpath in full["output_files"]:
                                fpath = fpath.replace("\\", "/")
                                fname = fpath.split("/")[-1]
                                artifacts.append({
                                    "title": f"Code Output: {fname}",
                                    "type": "image" if fname.lower().endswith((".png", ".jpg", ".gif")) else "file",
                                    "summary": full.get("stdout", "")[:200],
                                    "data": {"output_file": fpath},
                                    "output_files": [fpath],
                                    "source_file": getattr(session, 'loaded_file_path', ''),
                                })
                        elif "summary" in full:
                            artifact = {
                                "title": _make_artifact_title(name, args, full),
                                "type": full.get("type", "numerical"),
                                "summary": full.get("summary", ""),
                                "data": full.get("data"),
                                "output_files": full.get("output_files", []),
                                "source_file": getattr(session, 'loaded_file_path', ''),
                            }
                            artifacts.append(artifact)
                            # Auto-create image artifact for GIF output
                            gif_file = (full.get("data") or {}).get("gif_file")
                            if gif_file:
                                gif_file = gif_file.replace("\\", "/")
                                artifacts.append({
                                    "title": "GIF: " + gif_file.split("/")[-1],
                                    "type": "image",
                                    "summary": full.get("summary", ""),
                                    "data": {"output_file": gif_file},
                                    "output_files": [gif_file],
                                    "source_file": getattr(session, 'loaded_file_path', ''),
                                })
                except json.JSONDecodeError:
                    result = raw
                    full = None
            else:
                result = json.dumps({"error": f"Unknown tool: {name}"})
                full = None

            # Record signature only for executed calls — blocked or unknown
            # responses stay off the record so a retry after correction
            # is not itself flagged as a duplicate.
            last_tool_sig = sig
            session.messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })

            yield {"type": "tool_result", "tool": name,
                   "summary": full.get("summary", "") if isinstance(full, dict) else ""}

    yield {"type": "done", "content": "Maximum rounds reached.", "artifacts": artifacts}

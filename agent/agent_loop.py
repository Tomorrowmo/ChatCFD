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

"""MCP tool: calculate — Dispatcher entry for all registered algorithms."""

import json


def register(mcp, engine):
    @mcp.tool()
    def calculate(method: str, params: str = "{}", zone_name: str = "", session_id: str = "default") -> dict:
        """执行 CFD 算法（dispatcher）。具体算法注册在 post_service/algorithms/。

        **重要**：params 必须是 **JSON 字符串**，不是 dict 对象。
        例如 params='{"scalar":"Pressure","direction":0}'。

        参数:
            method: 算法名。不确定时先调 getMethodTemplate() 查全部 method
                    + 每个 method 的参数模板。
            params: JSON 字符串。不传用算法默认值。不确定参数调
                    getMethodTemplate(method) 查模板。
            zone_name: 目标 zone。大多数算法必填（statistics/render 可省略）。
                       从 loadFile 返回的 zones 列表中选。

        返回:
            {"type": str, "summary": str, "data": {...}, "output_files": [...]}
            失败时返回 {"error": "..."}，据此修正参数重试。
        """
        print(f"[MCP.calculate] method={method}, params={params!r}, zone_name={zone_name!r}, session_id={session_id!r}")
        parsed_params = json.loads(params)
        result = engine.calculate(session_id, method, parsed_params, zone_name)
        print(f"[MCP.calculate] result keys: {list(result.keys()) if isinstance(result, dict) else type(result)}")
        return result

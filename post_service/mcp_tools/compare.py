"""MCP tool: diffZones — Compare scalars between zones (same file or cross-file)."""


def register(mcp, engine):
    @mcp.tool()
    def diffZones(source_a: str, source_b: str, session_id: str = "default",
                  file_b: str = "") -> dict:
        """对比标量统计。支持同文件 zone 对比 或 跨文件 zone 对比。

        参数:
            source_a: "zone:scalar" 格式，如 "wall:Pressure"
            source_b: "zone:scalar" 格式，scalar 必须与 source_a 相同
            file_b: 跨文件对比时第二个文件的路径（必须已 loadFile 加载）。
                    不传或空字符串 = 同文件 zone 对比。

        返回:
            {"type":"comparison", "summary":..., "data":{...}}
        """
        return engine.compare(session_id, source_a, source_b, file_b=file_b)

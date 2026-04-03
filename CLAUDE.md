# ChatCFD

ChatCFD 是基于 AI 的 CFD 仿真数据智能分析平台。用户通过自然语言对话分析 CFD 仿真数据。

## 开发前必读

- `docs/chatcfd-prd.md` — 完整 PRD（18 章）。任何开发工作开始前，先读 PRD 中与当前任务相关的章节。
- `docs/agent-framework-analysis.md` — Agent 框架选型分析 + 整体架构详解（模块组成、数据关系、子 Agent 模型）。
- 当前阶段：**Phase 1**（核心能力），详见 PRD 第 17 章。

## 技术栈

- **后处理服务**: FastAPI + FastMCP (Python)，一个 HTTP 服务两类端点（MCP SSE + HTTP API）
- **计算引擎 (PostEngine)**: Session Manager + PostData 薄封装 + 算法注册表 + VTK 层
- **Agent**: 自研 Python（FastAPI WebSocket）+ LiteLLM（多 LLM 统一调用）+ mcp SDK（MCP Client）
- **VTK**: 9.4.1 + 自研 C++ 模块（RomtekIODriver / RomtekAnalysis / RomtekVtkAlgorithm）
- **前端**: Vue.js + VTK.js
- **Python 环境**: conda activate PostProcessTool

## 项目结构

```
chatcfd/
├── CLAUDE.md
├── docs/
│   ├── chatcfd-prd.md                 # 完整 PRD（18 章）
│   └── agent-framework-analysis.md    # 框架选型 + 架构详解
├── agent/                             # Agent 服务层
│   ├── main.py                        # FastAPI 入口（WebSocket + HTTP）
│   ├── agent_loop.py                  # 核心对话循环（LLM + tool dispatch）
│   ├── mcp_client.py                  # MCP Client（SSE 长连接）
│   ├── harness.py                     # Harness 硬约束（路径白名单/大小限制/Coding确认）
│   ├── session.py                     # Agent 侧会话管理（AgentSession + SessionPool）
│   ├── skills.py                      # Skill 工作流（从 MCP Prompt 加载，注入 System Prompt）
│   ├── insight_log.py                 # 需求洞察日志（JSONL，记录 resolution 分类）
│   └── sub_agent.py                   # 子 Agent（Phase 3：对比/Coding/报告）
├── post_service/                      # 后处理服务（一个 HTTP 服务）
│   ├── server.py                      # FastAPI + FastMCP 入口
│   ├── mcp_tools/                     # MCP 端点层（薄壳，给 Agent/LLM）
│   │   ├── load_file.py               # loadFile → engine.load_file()
│   │   ├── calculate.py               # calculate → engine.calculate()
│   │   ├── compare.py                 # compare → engine.compare()
│   │   ├── export_data.py             # exportData → engine.export_data()
│   │   ├── list_files.py              # listFiles → engine.list_files()
│   │   └── get_method_template.py     # getMethodTemplate → engine.get_method_template()
│   ├── http_api/                      # HTTP API 端点层（薄壳，给前端直连大数据）
│   │   ├── mesh.py                    # GET /api/mesh/{session}/{zone}
│   │   ├── scalar.py                  # GET /api/scalar/{session}/{zone}/{name}
│   │   ├── file.py                    # GET /api/file/{path}
│   │   └── upload.py                  # POST /api/upload
│   ├── engine.py                      # PostEngine 计算引擎（核心逻辑）
│   ├── session.py                     # SessionState + Session Manager
│   ├── post_data.py                   # PostData 薄封装层（零拷贝 + 物理量映射）
│   ├── algorithm_registry.py          # 算法注册表（自动扫描 algorithms/）
│   ├── algorithms/                    # 算法插件目录
│   │   ├── force_moment.py            # 力/力矩积分（VTK C++）
│   │   ├── velocity_gradient.py       # 速度梯度/涡量/Cp/马赫（VTK C++）
│   │   └── statistics.py              # 标量统计 min/max/mean（numpy）
│   └── config/
│       └── physical_mapping.json      # 物理量名称映射表
├── web/                               # Vue.js + VTK.js 前端
└── legacy/                            # 旧代码参考（不运行）
```

## 关键设计决策

1. **后处理服务双端点**: 一个 HTTP 服务，MCP SSE（给 LLM，返回 summary 小数据）+ HTTP API（给前端，返回网格/标量大数据）
2. **PostEngine 计算引擎**: MCP 端点和 HTTP API 端点都调用同一个 PostEngine，共享 Session Manager
3. **6 个 MCP 工具**: loadFile / calculate / compare / exportData / listFiles / getMethodTemplate
4. **统一返回格式**: {type, summary, data, output_files}，LLM 只看 summary
5. **算法插件化**: algorithms/ 目录，每个 .py 提供 NAME/DESCRIPTION/DEFAULTS/execute()
6. **PostData 薄封装**: 零拷贝 vtk_to_numpy，writeable=False 保护
7. **物理量映射表**: config/physical_mapping.json，PostData 层自动将标准名映射到文件实际标量名
8. **AI 约束三层**: Harness(硬) > Skill(中) > Prompt(软)
9. **前端双通道**: 对话走 Agent → MCP，渲染数据前端直连 HTTP API，不经过 LLM
10. **前端 Artifact 侧边栏 + VTK.js 3D 渲染**

## legacy/ 说明

legacy/ 下是旧项目的代码，不直接运行，仅作参考。迁移算法时参考这些文件：
- `legacy/PostDrive/PostDrive.py` — 文件读取驱动，封装 vtkRomtekIODriver
- `legacy/PostDrive/PostIntegral.py` — 力矩积分 Python 封装
- `legacy/PostDrive/PostVelocityGradient.py` — 速度梯度计算封装
- `legacy/PostDrive/ForceMomentIntegralStruct.py` — 力矩积分参数结构（将改为 DEFAULTS dict）
- `legacy/PostDrive/VelocityGradientStruct.py` — 速度梯度参数结构（将改为 DEFAULTS dict）
- `legacy/PostDrive/MultiBlockDataSetAnalyse.py` — 数据集分析
- `legacy/quick_tools.py` — 旧的 MCP 工具，参考缓存逻辑和 _ensure_loaded
- `legacy/tool.py` — 旧的工具函数
- `legacy/post_integral.py` — 力矩积分独立脚本
- `legacy/agent.py` — 旧的 Agent Loop + MCP Client 连接模式
- `legacy/VtkWidget.py` — VTK 渲染窗口（前端参考）

## 编码规范

- 所有 MCP tool 返回 dict，包括错误分支：`return {"error": "..."}`
- MCP 端点是薄壳：只做参数解析 → 调 engine.xxx() → 返回结果，不含业务逻辑
- 算法参数用 DEFAULTS dict，不用 class，不用逐字段 if-else
- Tool description 一句话，工具间描述互斥
- 路径统一 normpath + replace('\\', '/')
- VTK 相关代码集中在 post_service/ 层，agent/ 层不直接依赖 VTK
- get_scalar() 返回的 numpy 数组设 writeable=False

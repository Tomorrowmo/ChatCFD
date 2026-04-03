# Agent 框架选型深入分析

## 目录

- [一、Agent 层的 10 个核心职责（从 PRD 提取）](#一agent-层的-10-个核心职责从-prd-提取)
- [二、逐框架深入对比](#二逐框架深入对比)
  - [1. LangGraph（LangChain 生态）](#1-langgraphlangchain-生态)
  - [2. OpenAI Agents SDK / Claude Agent SDK](#2-openai-agents-sdk--claude-agent-sdk)
  - [3. Pydantic-AI](#3-pydantic-ai)
  - [4. CrewAI / AutoGen](#4-crewai--autogen)
  - [5. LiteLLM（不是 Agent 框架，是 LLM 网关）](#5-litellm不是-agent-框架是-llm-网关)
- [三、关键决策矩阵](#三关键决策矩阵)
- [四、最终建议](#四最终建议)
- [五、整体架构详解：模块组成与数据关系](#五整体架构详解模块组成与数据关系)
  - [5.1 全局数据流总览](#51-全局数据流总览)
  - [5.2 Agent 服务层内部组成](#52-agent-服务层内部组成)
  - [5.3 后处理服务内部组成](#53-后处理服务内部组成)
  - [5.4 模块间数据关系图](#54-模块间数据关系图)
  - [5.5 会话生命周期与对象关系](#55-会话生命周期与对象关系)
  - [5.6 Harness 拦截点详解](#56-harness-拦截点详解)
  - [5.7 算法执行路径对比：轻型 vs 重型](#57-算法执行路径对比轻型-vs-重型)
  - [5.8 子 Agent 交互模型（Phase 3）](#58-子-agent-交互模型phase-3)
  - [5.9 AI Coding 完整流程](#59-ai-coding-完整流程)
  - [5.10 Agent 决策流程（反问确认机制）](#510-agent-决策流程反问确认机制)
  - [5.11 前端内部组成](#511-前端内部组成)
  - [5.12 分析存档（Analysis Archive）](#512-分析存档analysis-archive)
  - [5.13 约束三层协作完整示例](#513-约束三层协作完整示例)
  - [5.14 Insight Log 记录结构](#514-insight-log-记录结构)
  - [5.15 依赖清单](#515-依赖清单)

---

## 一、Agent 层的 10 个核心职责（从 PRD 提取）

| # | 职责 | 复杂度 | PRD 位置 |
|---|------|--------|---------|
| 1 | **对话循环** — LLM 调用 → tool_call 解析 → 执行 → 结果反馈 | 低 | §2.2 |
| 2 | **MCP Client** — SSE 长连接，tool_call → MCP 协议转换 | 低 | §2.3 |
| 3 | **多 LLM 后端** — Qwen / Claude / GPT，统一接口 | 中 | §2.4 |
| 4 | **Harness 拦截** — 路径白名单、文件大小、返回值截断、Coding 确认 | 中 | §6.1 |
| 5 | **Skill 工作流** — 6 种固化流程，MCP Prompt 注入 | 低 | §6.2 |
| 6 | **WebSocket 服务** — 前端对话通信 | 中 | §2.1 |
| 7 | **文件上传暂存** — HTTP multipart → 暂存 → 转发路径 | 低 | §2.2.2 |
| 8 | **Insight Log** — 每次对话记录 resolution 分类 | 低 | §16 |
| 9 | **子 Agent**（Phase 3）— 3 种场景，干净上下文，只返回摘要 | 中 | §11 |
| 10 | **流式输出** — LLM 流式响应 → WebSocket 推送 | 中 | 隐含需求 |

---

## 二、逐框架深入对比

### 1. LangGraph（LangChain 生态）

**适配点：**
- 状态机模型天然适合"决策流程"（§15.2 的 Skill 匹配 → method 匹配 → exportData → AI Coding → 兜底）
- 内置 checkpointing，可以做对话持久化
- 支持子图（subgraph），理论上可以映射子 Agent
- LangSmith 可观测性，直接对应 Insight Log 的部分需求

**不适配点：**
- **Harness 没有对应概念**。LangGraph 的节点是"状态转移"，不是"拦截器"。Harness 需要在 tool_call 之前/之后插入检查，这在 LangGraph 里要么做成额外节点（打断流程），要么 hack 到 tool executor 里（违背框架设计）
- **MCP 是外来物种**。LangGraph 的工具体系是 `@tool` 装饰器 + ToolNode，要用 MCP 工具就需要做一层适配：MCP tool → LangGraph tool wrapper。每次 MCP 工具增减，适配层也要跟着变
- **多 LLM 后端**需要通过 `langchain-community` 的各种 ChatModel，每个后端一个适配包，版本兼容是长期痛点
- **重**。langchain-core + langgraph + langchain-openai + langchain-community，依赖树深，调试时堆栈很长
- **学习曲线**。状态机、条件边、checkpoint、StreamMode 等概念，团队需要一周左右上手

**代码量对比：**

```python
# 自研：对话循环 ~30 行
while True:
    response = llm.chat(messages, tools=mcp_tools)
    if not response.tool_calls: break
    for tc in response.tool_calls:
        result = harness.check_then_call(tc)  # Harness 拦截
        messages.append(tool_result(tc.id, result))

# LangGraph：需要定义状态、节点、边 ~80-100 行
class AgentState(TypedDict):
    messages: list
    
def should_continue(state): ...
def call_model(state): ...
def call_tools(state): ...  # 这里还要套 MCP 适配层 + Harness 逻辑

graph = StateGraph(AgentState)
graph.add_node("agent", call_model)
graph.add_node("tools", call_tools)
graph.add_conditional_edges("agent", should_continue, ...)
```

**结论**：引入 LangGraph 会让简单的对话循环变复杂，且 Harness/MCP 都需要额外适配层。状态机模型对 Phase 3 子 Agent 有帮助，但 Phase 1-2 是过度工程。

---

### 2. OpenAI Agents SDK / Claude Agent SDK

**适配点：**
- 轻量，API 简洁
- 原生 tool calling，和 LLM 的 function calling 协议完全一致
- OpenAI Agents SDK 有 `handoff`（转交）概念，可以映射子 Agent

**不适配点：**
- **单一 LLM 绑定**。OpenAI SDK 绑定 OpenAI API 格式，Claude SDK 绑定 Anthropic API。需要支持 Qwen（通义）作为主要后端，这两个 SDK 都不原生支持
- **工具系统冲突**。这些 SDK 有自己的 `@tool` 注册机制，工具在 MCP Server 上。要么把 MCP 工具逐个包装成 SDK tool（维护成本），要么放弃 SDK 的工具系统（那就失去了用 SDK 的主要意义）
- **Harness 无位置**。SDK 控制的是"Agent 如何选工具"，不控制"工具执行前后的拦截"

**结论**：如果只用一个 LLM 后端且不需要 MCP，这些 SDK 是好选择。但两个前提都不满足。

---

### 3. Pydantic-AI

**适配点：**
- **多模型支持最好**。原生支持 OpenAI、Anthropic、Gemini、Ollama、Mistral 等，通义千问走 OpenAI 兼容接口也能用
- 类型安全，参数校验强
- 轻量，不像 LangChain 那么重
- 有 `@agent.tool` 装饰器，但也支持动态工具注册

**不适配点：**
- **MCP 工具适配仍需要**。Pydantic-AI 有实验性的 MCP 支持（`MCPServerHTTP`），但文档标注为 beta，且只支持 Streamable HTTP，不支持 SSE transport（MCP Server 用的是 SSE）
- **Harness 需要 hook 进去**。Pydantic-AI 没有 "before_tool_call / after_tool_call" 的 hook 点。需要在 tool wrapper 里手动加，或者 monkey-patch
- **Skill 工作流不好表达**。Pydantic-AI 的核心是"Agent = system prompt + tools + structured output"，没有"工作流"概念。Skill 还是得靠 prompt 注入
- **子 Agent 支持弱**。没有 handoff 或 sub-agent 原语

**代码量对比：**

```python
# Pydantic-AI
from pydantic_ai import Agent

agent = Agent('openai:qwen-plus', system_prompt=SYSTEM)

# 每个 MCP 工具都要包装一次
@agent.tool
async def load_file(ctx, file_path: str) -> str:
    # harness check
    if not harness.check_path(file_path):
        return {"error": "path not allowed"}
    return await mcp_client.call("loadFile", {"file_path": file_path})

# 自研：tool dispatch 集中处理
async def dispatch_tool(name, args):
    error = harness.before_call(name, args)
    if error: return error
    result = await mcp_client.call(name, args)
    return harness.after_call(name, result)  # 截断等
```

**结论**：Pydantic-AI 在多模型支持上最接近需求，但 MCP SSE transport 不支持、Harness hook 缺失是硬伤。如果这两个问题未来被修复，Phase 2-3 可以重新评估。

---

### 4. CrewAI / AutoGen

**适配点：**
- 多 Agent 协作是核心能力
- 有 role/goal/backstory 等角色定义

**不适配点：**
- **Phase 1-2 完全不需要多 Agent**。PRD 明确说"Phase 1-2 全部由主 Agent 直接处理"
- **重型框架**，引入了大量不需要的概念（crew、task、process、delegation）
- **MCP 不是一等公民**
- **多 LLM 后端**支持参差不齐

**结论**：完全不适合。多 Agent 需求极简（3 个固定场景），不需要通用多 Agent 框架。

---

### 5. LiteLLM（不是 Agent 框架，是 LLM 网关）

**适配点：**
- **精确解决多 LLM 后端问题**。统一接口调用 Qwen/Claude/GPT/Ollama，一行代码切换
- **不侵入架构**。只负责 LLM 调用，不碰工具系统、不碰 Agent 循环
- 支持流式、function calling、token 计数
- 可以做 fallback（Qwen 挂了自动切 GPT）

**不适配点：**
- 不解决 Agent 循环、Harness、Skill 等问题（但这些本来就不该框架管）

**代码量影响：**

```python
# 不用 LiteLLM：每个后端要写适配
if provider == "qwen":
    client = OpenAI(base_url="https://dashscope...")
elif provider == "claude":
    client = Anthropic(...)
elif provider == "gpt":
    client = OpenAI(...)
# tool_call 格式还有微妙差异...

# 用 LiteLLM：一行
import litellm
response = litellm.completion(model="qwen/qwen-plus", messages=messages, tools=tools)
# 或 model="claude-3-sonnet", model="gpt-4o"，接口完全一致
```

---

## 三、关键决策矩阵

| 职责 | 自研成本 | 框架能帮多少 | 最佳方案 |
|------|:-------:|:-----------:|---------|
| 对话循环 | 30 行 | 框架反而更复杂 | **自研** |
| MCP Client | mcp SDK 已解决 | 框架有冲突 | **mcp SDK** |
| 多 LLM 后端 | 100-150 行适配 | LiteLLM 直接解决 | **LiteLLM** |
| Harness 拦截 | 100 行 | 框架没有对应概念 | **自研** |
| Skill 工作流 | MCP Prompt | 框架无优势 | **MCP Prompt** |
| WebSocket 服务 | FastAPI/Starlette | 与 Agent 框架无关 | **FastAPI** |
| 文件上传 | FastAPI route | 与 Agent 框架无关 | **FastAPI** |
| Insight Log | 50 行 JSONL 写入 | LangSmith 可选但重 | **自研** |
| 子 Agent (P3) | 50-80 行 | 框架有帮助但引入太多不需要的东西 | **自研** |
| 流式输出 | SSE/WS 推送 | 框架反而限制控制粒度 | **自研** |

---

## 四、最终建议

```
推荐方案：自研 Agent + LiteLLM
```

**架构：**

```
┌─────────────────────────────────────────┐
│  Agent 服务层 (FastAPI)                  │
│  ┌─ FastAPI (WebSocket + HTTP) ───────┐ │
│  ├─ Harness（before/after hook）      │ │  ← 自研，100 行
│  ├─ Agent Loop（对话循环 + dispatch） │ │  ← 自研，150 行
│  │      ├── LiteLLM ← 统一 LLM 调用  │ │  ← 三方库，0 行适配
│  │      └── mcp SDK ← MCP tool 调用  │ │  ← 官方 SDK
│  ├─ Skill（MCP Prompt 注入）          │ │  ← prompt 文本
│  └─ Insight Log（JSONL）              │ │  ← 自研，50 行
└───────────────────┬───────────────────┘ │
                    │ MCP SSE             │
┌───────────────────▼───────────────────┐ │
│  后处理服务 (FastAPI + FastMCP)        │ │
│  ┌─ MCP 端点（薄壳）────────────────┐ │ │  ← 6 个 tool，调 engine
│  ├─ HTTP API 端点（薄壳）───────────┤ │ │  ← 前端直连，调 engine
│  ├─ PostEngine（计算引擎）──────────┤ │ │  ← 核心逻辑
│  │    Session Manager + PostData    │ │ │
│  │    算法注册表 + algorithms/      │ │ │
│  └─ VTK 层（C++ 模块）─────────────┘ │ │
└───────────────────────────────────────┘ │
```

**核心理由：**

1. **Harness 是自研必须品** — 没有任何框架提供 "tool_call 前后拦截" 且和 MCP 工具体系兼容。这一层决定了 Agent 框架无法直接套用

2. **MCP 是工具协议** — 引入框架等于引入第二套工具系统，两者之间需要适配层。适配层本身就和自研一个 agent loop 的工作量差不多

3. **LiteLLM 精准解决唯一的痛点** — 多 LLM 后端统一。不侵入架构，不增加概念负担。将来换模型、加 fallback、做 A/B 测试都方便

4. **Phase 3 子 Agent 不需要框架** — PRD 定义了只有 3 种固定场景，每种子 Agent 就是"创建新的 LLM 对话 + 给任务描述 + 拿回摘要"，50 行代码能搞定

5. **总代码量对比**：自研 Agent 层预估 300-400 行 vs 引入框架 + 适配 MCP + 适配 Harness 预估 500-700 行 + 框架学习成本

---

## 五、整体架构详解：模块组成与数据关系

### 5.1 全局数据流总览

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              用户浏览器                                   │
│  ┌────────────┐  ┌──────────┐  ┌──────────────────┐  ┌──────────────┐  │
│  │  对话输入框  │  │ 文件上传  │  │ Artifact 侧边栏  │  │ VTK.js 3D    │  │
│  └─────┬──────┘  └────┬─────┘  └────────▲─────────┘  └──────▲───────┘  │
│        │ ①            │ ②               │ ⑦                 │ ⑧        │
└────────┼──────────────┼────────────────┼─────────────────────┼──────────┘
         │WS            │HTTP             │WS                   │HTTP
         │(文本)        │(multipart)      │(结构化结果)          │(网格/标量)
         │              │                 │                     │
┌────────▼──────────────▼─────────────────┼─────────────────────┼──────────┐
│                    Agent 服务层           │                     │          │
│                                          │                     │          │
│  ③ Harness ──拦截──→ ④ Agent Loop ───────┘                     │          │
│                          │    │                                │          │
│                     ⑤ LiteLLM │                                │          │
│                     (→ LLM)   │ ⑥ mcp SDK                     │          │
│                               │ (tool_call)                    │          │
└───────────────────────────────┼────────────────────────────────┼──────────┘
                                │MCP (SSE)                       │HTTP API
                                │(summary 小数据)                │(大数据)
                                │                                │
┌───────────────────────────────▼────────────────────────────────▼──────────┐
│                         后处理服务（一个 HTTP 服务）                        │
│                                                                           │
│  ┌──────────────────┐    ┌──────────────────────────┐    ← 接口层（薄） │
│  │ MCP 端点 (SSE)    │    │ HTTP API 端点             │                    │
│  │ 6 tools → summary │    │ GET /mesh → 网格几何      │                    │
│  └────────┬─────────┘    │ GET /scalar → 标量数组     │                    │
│           │               │ GET /file → 文件下载       │                    │
│           │               └────────────┬─────────────┘                    │
│           └──────────┬─────────────────┘                                  │
│                      ▼                                                    │
│  ┌────────────────────────────────────────────────────────┐  ← 核心层   │
│  │  PostEngine（计算引擎，核心逻辑全在这里）                │              │
│  │                                                        │              │
│  │  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐ │              │
│  │  │Session Manager│  │ PostData     │  │ 算法注册表   │ │              │
│  │  │session_id →   │  │ 薄封装+映射  │  │ METHODS{}   │ │              │
│  │  │SessionState   │  │ 零拷贝访问   │  │ 插件自动扫描 │ │              │
│  │  └──────────────┘  └──────────────┘  └─────────────┘ │              │
│  │                                                        │              │
│  │  ┌─────────────────────────────────────────────────┐  │              │
│  │  │ VTK 层（IO + Filters，C++ 模块）                 │  │              │
│  │  │ RomtekIODriver │ ForceMomentIntegtal │ ...       │  │              │
│  │  └─────────────────────────────────────────────────┘  │              │
│  └────────────────────────────────────────────────────────┘              │
│                                                                           │
│  ┌────────────────────────────────────────────────────────┐  ← 存储层   │
│  │  文件存储（用户数据 + 输出文件） + 分析存档(.chatcfd/)   │              │
│  └────────────────────────────────────────────────────────┘              │
└───────────────────────────────────────────────────────────────────────────┘
```

**数据流编号说明：**

| # | 数据内容 | 协议 | 数据量 | 方向 |
|---|---------|------|:------:|------|
| ① | 用户自然语言输入 | WebSocket | ~100 tokens | 前端 → Agent |
| ② | CFD 数据文件（.cgns/.plt 等） | HTTP multipart | MB~GB | 前端 → Agent → 文件暂存 |
| ③ | Harness 拦截检查（路径/大小/黑名单） | 函数调用 | - | Agent 内部 |
| ④ | LLM 的 tool_call 指令 + Agent 组装回复 | Agent 内部 | ~200 tokens | Agent Loop 核心 |
| ⑤ | 对话消息 + tool definitions → LLM 响应 | HTTP (LLM API) | ~1K-8K tokens | Agent ↔ LLM |
| ⑥ | tool_call → MCP 端点 → PostEngine 执行 → 返回 `{summary, data}` | SSE (MCP) | summary ~200 tokens | Agent ↔ MCP 端点 → PostEngine |
| ⑦ | 结构化结果（JSON 卡片、表格、文件路径） | WebSocket | ~1K tokens | Agent → 前端 |
| ⑧ | 网格几何数据、标量数组、文件下载 | HTTP API | KB~数十MB | HTTP API 端点 → PostEngine → 前端 |

**关键设计：前端双通道**
- **对话通道**（① → ③ → ④ → ⑤ → ⑥ → ⑦）：文本和小数据，走 Agent + LLM + MCP，LLM 只看 summary
- **数据通道**（⑧）：3D 渲染和大数据，前端直连 HTTP API，不经过 LLM，不消耗 token

---

### 5.2 Agent 服务层内部组成

```
agent/
├── main.py                    # FastAPI 应用入口
│   ├── WebSocket /ws          # 对话端点
│   ├── POST /upload           # 文件上传端点
│   └── startup/shutdown       # 生命周期管理
│
├── agent_loop.py              # 核心对话循环（~150 行）
│   ├── run(messages, session)
│   │   ├── while True:
│   │   │   ├── litellm.completion()     → ⑤ 调 LLM
│   │   │   ├── parse tool_calls
│   │   │   ├── harness.before_call()    → ③ 前置拦截
│   │   │   ├── mcp_client.call_tool()   → ⑥ 调 MCP
│   │   │   ├── harness.after_call()     → 返回值截断
│   │   │   └── append tool_result
│   │   └── return final_response
│   └── stream_run()           # 流式版本（SSE 推送给前端）
│
├── mcp_client.py              # MCP 连接管理（~80 行）
│   ├── MCPClient
│   │   ├── connect(session_id)          → 建立 SSE 长连接
│   │   ├── list_tools() → list[Tool]    → 启动时获取工具列表
│   │   ├── call_tool(name, args) → dict → 执行 MCP 工具
│   │   ├── get_prompts() → list         → 获取 Skill 工作流
│   │   └── close()                      → 关闭连接
│   └── tool_format_convert()            → MCP 工具 → LLM function 格式
│
├── harness.py                 # 硬约束拦截（~100 行）
│   ├── Harness
│   │   ├── before_call(tool_name, args) → Optional[dict]
│   │   │   ├── check_path_whitelist()   → 路径白名单
│   │   │   ├── check_file_size()        → 文件大小限制
│   │   │   ├── check_coding_confirm()   → AI Coding 需用户确认
│   │   │   └── check_command_blacklist() → 危险命令拦截
│   │   └── after_call(tool_name, result) → dict
│   │       └── truncate_for_llm()       → 超长返回值截断
│   └── HarnessConfig                    → 白名单、黑名单、限制值配置
│
├── session.py                 # Agent 侧会话管理（~60 行）
│   ├── AgentSession
│   │   ├── session_id: str
│   │   ├── messages: list               → 对话历史
│   │   ├── mcp_client: MCPClient        → 该会话的 MCP 连接
│   │   ├── user_confirmed_coding: bool  → AI Coding 确认标记
│   │   └── created_at / last_active     → 超时管理
│   └── SessionPool
│       ├── get(session_id) → AgentSession
│       ├── create(session_id) → AgentSession
│       └── cleanup_expired()            → 定时清理
│
├── skills.py                  # Skill 工作流管理（~40 行）
│   ├── load_skills_from_mcp()           → 从 MCP Prompt 获取 Skill 定义
│   └── build_system_prompt(skills)      → 拼装 System Prompt
│       ├── 身份提示（Prompt 软约束）
│       ├── Skill 工作流注入（中约束）
│       └── 行为规范（不编造/简洁/单位等）
│
├── insight_log.py             # 需求洞察日志（~50 行）
│   ├── log_query(session_id, user_input, resolution, tools_called)
│   │   └── 追加写入 .chatcfd/insight_log.jsonl
│   └── resolution 分类:
│       ├── skill_matched    → Skill 直接命中
│       ├── tool_resolved    → 工具组合解决
│       ├── params_clarified → 反问后解决
│       ├── fallback_coding  → 降级为 AI Coding
│       ├── unresolved       → 未解决
│       └── error            → 工具报错
│
└── sub_agent.py               # 子 Agent（Phase 3，~80 行）
    ├── create_sub_agent(task_description, mcp_client)
    │   └── 干净 messages + 独立 LLM 调用 + 共享 mcp_client
    ├── CompareSubAgent        → 多文件对比
    ├── CodingSubAgent         → AI Coding 隔离执行
    └── ReportSubAgent         → 完整报告生成
```

---

### 5.3 后处理服务内部组成

后处理服务是**一个 HTTP 服务**，内部分三层：**接口层（薄）→ 计算引擎（PostEngine）→ 存储层**。
MCP 端点和 HTTP API 端点都只是接口壳，核心逻辑全在 PostEngine 里。

```
post_service/                  # 后处理服务（一个进程）
│
│  ══════════════════════════════════════════════════════════════
│  接口层（薄壳，只做协议转换，不含业务逻辑）
│  ══════════════════════════════════════════════════════════════
│
├── server.py                  # 服务入口（FastAPI + FastMCP 挂载）
│   ├── app = FastAPI()
│   ├── mcp = FastMCP()
│   └── app.mount("/mcp", mcp.sse_app())   → MCP 和 HTTP 共用一个进程
│
├── mcp_tools/                 # MCP 端点层 — 给 Agent/LLM（返回 summary 小数据）
│   │                          # 每个 tool 是一个薄壳：解析参数 → 调 PostEngine → 返回结果
│   │
│   ├── load_file.py           → @mcp.tool() loadFile(file_path)
│   │   └── engine.load_file(session_id, file_path) → summary
│   │
│   ├── calculate.py           → @mcp.tool() calculate(method, params, zone_name)
│   │   └── engine.calculate(session_id, method, params, zone_name) → {summary, data}
│   │
│   ├── compare.py             → @mcp.tool() compare(source_a, source_b, ...)
│   │   └── engine.compare(session_id, ...) → 差异摘要
│   │
│   ├── export_data.py         → @mcp.tool() exportData(zone, scalars, format)
│   │   └── engine.export_data(session_id, ...) → 文件路径
│   │
│   ├── list_files.py          → @mcp.tool() listFiles(directory, suffix)
│   │   └── engine.list_files(...) → 文件列表
│   │
│   └── get_method_template.py → @mcp.tool() getMethodTemplate(method)
│       └── engine.get_method_template(method) → 参数模板
│
├── http_api/                  # HTTP API 端点层 — 给前端直连（返回网格/标量等大数据）
│   │                          # 前端渲染需要几十 MB 数据，不能走 Agent → LLM 通道
│   │
│   ├── mesh.py                → GET /api/mesh/{session_id}/{zone}
│   │   └── engine.get_mesh_geometry(session_id, zone) → 网格几何（JSON/binary）
│   │
│   ├── scalar.py              → GET /api/scalar/{session_id}/{zone}/{name}
│   │   └── engine.get_scalar_data(session_id, zone, name) → 标量数组
│   │
│   ├── file.py                → GET /api/file/{path}
│   │   └── 文件下载（CSV/VTM/PNG）
│   │
│   └── upload.py              → POST /api/upload
│       └── 文件上传暂存
│
│  ══════════════════════════════════════════════════════════════
│  PostEngine（计算引擎，核心逻辑全在这里）
│  MCP 端点和 HTTP API 端点都调用同一个 PostEngine 实例
│  ══════════════════════════════════════════════════════════════
│
├── engine.py                  # PostEngine 入口（~200 行）
│   ├── PostEngine
│   │   ├── session_mgr: SessionManager
│   │   ├── algorithm_registry: dict[str, AlgorithmEntry]
│   │   │
│   │   ├── load_file(session_id, file_path) → dict
│   │   │   ├── VTK IO 读取文件 → vtkMultiBlockDataSet
│   │   │   ├── 创建 PostData 实例（薄封装 + 物理量映射）
│   │   │   ├── 缓存到 SessionState
│   │   │   └── 返回 summary（区域/标量/网格规模）
│   │   │
│   │   ├── calculate(session_id, method, params, zone_name) → dict
│   │   │   ├── 取缓存 SessionState.post_data
│   │   │   ├── 查注册表 METHODS[method]
│   │   │   ├── 合并参数 {**DEFAULTS, **user_params}
│   │   │   └── 调用 algorithm.execute(post_data, merged, zone_name)
│   │   │
│   │   ├── compare(session_id, ...) → dict
│   │   ├── export_data(session_id, ...) → dict
│   │   ├── list_files(...) → dict
│   │   ├── get_method_template(method) → dict
│   │   │
│   │   ├── get_mesh_geometry(session_id, zone) → bytes/dict  ← HTTP API 调用
│   │   └── get_scalar_data(session_id, zone, name) → bytes   ← HTTP API 调用
│   │
│   └── 关键设计：
│       MCP 端点调 engine.calculate() → 返回 summary（给 LLM 看，小数据）
│       HTTP API 调 engine.get_scalar_data() → 返回完整数组（给前端渲染，大数据）
│       两者共享同一个 SessionState，不重复计算
│
├── session.py                 # 会话状态管理
│   ├── SessionState
│   │   ├── post_data: PostData           → 薄封装层实例
│   │   ├── output_dir: str               → 输出目录（= 文件所在目录）
│   │   └── created_at / timeout_timer    → 超时自动清理
│   └── SessionManager
│       ├── sessions: dict[str, SessionState]
│       ├── get(session_id) → SessionState
│       ├── create(session_id, file_path) → SessionState
│       └── destroy(session_id)           → 释放 VTK 对象内存
│
├── post_data.py               # PostData 薄封装（~120 行）
│   ├── PostData
│   │   ├── _multiblock: vtkMultiBlockDataSet   → 持有 VTK 引用（不复制）
│   │   ├── _mapping: dict                      → 物理量映射表
│   │   ├── _resolved: dict                     → 缓存已解析的映射
│   │   │
│   │   ├── get_zones() → list[str]              → 区域名列表
│   │   ├── get_scalar(zone, name) → np.ndarray  → 零拷贝，writeable=False
│   │   ├── get_points(zone) → np.ndarray        → 节点坐标 (N,3)
│   │   ├── get_scalar_names(zone) → list[str]   → 标量名列表
│   │   ├── get_bounds(zone) → dict              → 包围盒
│   │   ├── get_summary() → dict                 → 精简摘要（给 LLM）
│   │   ├── get_vtk_data() → vtkMultiBlockDataSet → 底层对象（重型算法用）
│   │   │
│   │   └── _resolve_name(zone, name) → str      → 标准名 → 文件实际标量名
│   │       ├── 直接匹配 → 返回
│   │       ├── 查映射表 aliases → 返回
│   │       └── 都找不到 → raise ValueError + 列出可用标量
│   │
│   └── 物理量映射: config/physical_mapping.json
│       └── { "pressure": { aliases: ["Pressure","Static_Pressure","p",...] }, ... }
│
├── algorithms/                # 算法插件目录（自动扫描加载）
│   ├── force_moment.py        → NAME / DESCRIPTION / DEFAULTS / execute()
│   │   └── execute(): post_data.get_vtk_data() → ForceMomentIntegtal (C++)
│   │
│   ├── velocity_gradient.py   → NAME / DESCRIPTION / DEFAULTS / execute()
│   │   └── execute(): post_data.get_vtk_data() → CalculateVelocityGradient (C++)
│   │
│   ├── statistics.py          → NAME / DESCRIPTION / DEFAULTS / execute()
│   │   └── execute(): post_data.get_scalar() → numpy min/max/mean/std
│   │
│   └── (新增算法放这里，重启即生效)
│
├── algorithm_registry.py      # 算法注册表（~30 行）
│   ├── METHODS: dict[str, {description, defaults, execute}]
│   └── scan_and_load("algorithms/")    → 启动时自动扫描
│
│  ══════════════════════════════════════════════════════════════
│  VTK 层（C++ 模块 + Python 绑定，被 PostEngine 内部调用）
│  ══════════════════════════════════════════════════════════════
│
└── vtk_layer/
    ├── RomtekIODriver              → 多格式文件读取（CGNS/Tecplot/Ensight/VTK）
    ├── ForceMomentIntegtal         → 力/力矩积分
    ├── CalculateVelocityGradient   → 速度梯度/涡量/Cp/马赫
    ├── SliceFilter                 → 切片（Phase 3）
    ├── ContourPlaneFilter          → 等值面（Phase 3）
    ├── VectorFlowLineFilter        → 流线（Phase 3）
    ├── SurfaceFilter               → 表面提取（Phase 3）
    └── VolumeRenderFilter          → 体渲染（Phase 3）
```

---

### 5.4 模块间数据关系图

```
                    ┌──────────────────────────┐
                    │     LLM API (外部)        │
                    │  输入: messages + tools    │
                    │  输出: text / tool_calls   │
                    └─────────▲────┬────────────┘
                              │    │
              ⑤ completion()  │    │ tool_call{name, args}
                              │    │
┌─────────────────────────────┴────▼──────────────────────────────────────┐
│  Agent 服务层                                                           │
│                                                                         │
│  ┌─────────┐    ┌──────────────────────────────────────────────────┐   │
│  │ Session  │◄──►│ Agent Loop                                      │   │
│  │ Pool     │    │                                                  │   │
│  │          │    │  messages ──→ LiteLLM ──→ LLM API ──→ response  │   │
│  │ session  │    │                                                  │   │
│  │  ├ id    │    │  tool_call ──→ Harness.before() ──→ 拦截?       │   │
│  │  ├ msgs  │    │                   │ 通过                         │   │
│  │  ├ mcp   │    │                   ▼                              │   │
│  │  └ flags │    │              MCP Client.call_tool()              │   │
│  └─────────┘    │                   │                              │   │
│                  │                   ▼                              │   │
│                  │              Harness.after() → 截断              │   │
│                  │                   │                              │   │
│                  │                   ▼                              │   │
│                  │              append to messages                  │   │
│                  │              + Insight Log                       │   │
│                  └──────────────────────────────────────────────────┘   │
│                                      │                                  │
│  Skill (System Prompt 注入)           │                                  │
│  ┌──────────────────────────────┐    │                                  │
│  │ "用户提到文件名 → loadFile"   │    │                                  │
│  │ "用户说算力矩 → calculate"   │    │ 决定 LLM 选哪个 tool              │
│  │ "参数不确定 → 先反问"         │    │                                  │
│  └──────────────────────────────┘    │                                  │
└──────────────────────────────────────┼──────────────────────────────────┘
                                       │ MCP SSE
                                       │ tool_call(name, args)
                                       │ → {type, summary, data, output_files}
                                       │
┌──────────────────────────────────────▼──────────────────────────────────┐
│  后处理服务                                                              │
│                                                                         │
│  ┌─ 接口层（薄壳，只做协议转换）────────────────────────────────────────┐ │
│  │                                                                    │ │
│  │  MCP 端点:                                                         │ │
│  │    @mcp.tool() loadFile(...)   → engine.load_file(...)            │ │
│  │    @mcp.tool() calculate(...)  → engine.calculate(...)            │ │
│  │    @mcp.tool() compare(...)    → engine.compare(...)              │ │
│  │    ...                                                             │ │
│  │                                                                    │ │
│  │  HTTP API 端点:                                                    │ │
│  │    GET /api/mesh/...           → engine.get_mesh_geometry(...)     │ │
│  │    GET /api/scalar/...         → engine.get_scalar_data(...)      │ │
│  │    ...                                                             │ │
│  │                                                                    │ │
│  └──────────────────────────┬─────────────────────────────────────────┘ │
│                              │ 都调用同一个 PostEngine                   │
│                              ▼                                          │
│  ┌─ PostEngine（计算引擎）──────────────────────────────────────────────┐ │
│  │                                                                    │ │
│  │  engine.load_file():                                               │ │
│  │    VTK IO ──→ PostData 创建 ──→ SessionState.cache()              │ │
│  │    读文件       创建实例           缓存                              │ │
│  │                                                                    │ │
│  │  engine.calculate():                                               │ │
│  │    SessionState.post_data ──→ METHODS[method] ──→ execute()       │ │
│  │    取缓存                      查注册表              │              │ │
│  │                                              ┌──────┴──────┐       │ │
│  │                                              │             │       │ │
│  │                                         轻型算法       重型算法     │ │
│  │                                         get_scalar()  get_vtk_data()│ │
│  │                                         → numpy 运算  → C++ 运算   │ │
│  │                                              │             │       │ │
│  │                                              └──────┬──────┘       │ │
│  │                                                     ▼              │ │
│  │                                              {type, summary, data} │ │
│  │                                                                    │ │
│  │  engine.compare():                                                 │ │
│  │    两份 PostData.get_scalar() ──→ numpy 做差 ──→ 差异摘要          │ │
│  │                                                                    │ │
│  │  engine.export_data():                                             │ │
│  │    PostData.get_scalar()/get_points() ──→ 写文件                   │ │
│  │                                                                    │ │
│  │  engine.get_mesh_geometry():  ← HTTP API 调用                      │ │
│  │    PostData.get_vtk_data() ──→ 提取网格几何 ──→ 二进制/JSON        │ │
│  │                                                                    │ │
│  │  engine.get_scalar_data():    ← HTTP API 调用                      │ │
│  │    PostData.get_scalar() ──→ 完整 numpy 数组 ──→ 二进制            │ │
│  │                                                                    │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                              │ 调用                                     │
│                              ▼                                          │
│  ┌─ PostData 薄封装层 ─────────────────────────────────────────────────┐ │
│  │                                                                    │ │
│  │  上层调用 get_scalar("wall","pressure")                            │ │
│  │           │                                                        │ │
│  │           ▼  _resolve_name()                                       │ │
│  │  物理量映射表: "pressure" → ["Pressure","Static_Pressure","p"]     │ │
│  │           │                                                        │ │
│  │           ▼  在文件中查找匹配                                       │ │
│  │  vtk_to_numpy(vtkArray) → np.ndarray (零拷贝, writeable=False)    │ │
│  │           │                                                        │ │
│  │           ▼                                                        │ │
│  │  返回 numpy 数组（引用 VTK 内存，不复制）                           │ │
│  │                                                                    │ │
│  └──────────────────────────────┬─────────────────────────────────────┘ │
│                                  │ 持有引用                              │
│                                  ▼                                      │
│  ┌─ VTK 层 ───────────────────────────────────────────────────────────┐ │
│  │  vtkMultiBlockDataSet（唯一数据源，缓存在 SessionState）            │ │
│  │       │                                                            │ │
│  │       ├── Block[0] "solid" ── PointData: [Pressure, Velocity...]  │ │
│  │       ├── Block[1] "far"   ── PointData: [Pressure, Velocity...]  │ │
│  │       └── Block[2] "wall"  ── PointData: [Pressure, Velocity...]  │ │
│  └────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

---

### 5.5 会话生命周期与对象关系

```
时间轴 ──────────────────────────────────────────────────────────────────→

用户打开网页
    │
    ├─ 创建 session_id="abc123"
    │
    ├─ Agent 侧:
    │   └─ SessionPool.create("abc123")
    │       ├─ AgentSession { session_id, messages=[], mcp_client }
    │       └─ MCPClient.connect("abc123") ──→ SSE 长连接建立
    │
    ├─ 后处理服务侧:
    │   └─ SessionManager.create("abc123")
    │       └─ SessionState { post_data=None, output_dir=None }
    │
    ├─ 用户说 "分析 ysy.cgns"
    │   ├─ Agent Loop → LLM → tool_call: loadFile("ysy.cgns")
    │   ├─ Harness.before: 路径白名单 ✓
    │   ├─ MCP call loadFile
    │   │   → MCP 端点（薄壳）→ engine.load_file():
    │   │       ├─ RomtekIODriver 读文件 → vtkMultiBlockDataSet
    │   │       ├─ PostData(multiblock, "ysy.cgns") 创建
    │   │       ├─ SessionState.post_data = post_data  ← 缓存
    │   │       └─ 返回 summary
    │   ├─ Harness.after: 检查返回值长度 ✓
    │   └─ Agent 组装回复 → WS → 前端
    │
    ├─ 用户说 "算力矩"
    │   ├─ Agent Loop → LLM → tool_call: calculate("force_moment")
    │   ├─ MCP call calculate
    │   │   → MCP 端点（薄壳）→ engine.calculate():
    │   │       ├─ SessionState.post_data ← 复用缓存（不重新加载）
    │   │       ├─ METHODS["force_moment"].execute(post_data, params, zone)
    │   │       │   └─ post_data.get_vtk_data() → C++ ForceMomentIntegtal
    │   │       └─ 返回 {summary: "CL=0.35", data: {...}}
    │   └─ Agent → WS → 前端
    │       └─ 前端 Artifact: JSON 卡片展示力矩结果
    │
    ├─ 前端请求 3D 渲染（不经过 Agent/LLM，走 HTTP API 端点）
    │   ├─ GET /api/mesh/abc123/wall
    │   │   → HTTP API 端点 → engine.get_mesh_geometry() → 网格几何数据
    │   ├─ GET /api/scalar/abc123/wall/Pressure
    │   │   → HTTP API 端点 → engine.get_scalar_data() → 标量数组
    │   └─ VTK.js 渲染
    │   注意：PostEngine 是同一个实例，MCP 端点和 HTTP API 端点共享 SessionState
    │
    ├─ 用户关闭网页 / 超时
    │   ├─ Agent 侧:
    │   │   ├─ MCPClient.close() → SSE 连接断开
    │   │   └─ SessionPool.destroy("abc123")
    │   └─ 后处理服务侧:
    │       ├─ SessionManager.destroy("abc123")
    │       ├─ SessionState.post_data = None
    │       └─ vtkMultiBlockDataSet 释放 → 内存回收
    │
    ▼
```

---

### 5.6 Harness 拦截点详解

```
Agent Loop 中一次 tool_call 的完整生命周期：

    LLM 返回 tool_call: { name: "loadFile", args: { file_path: "..." } }
                │
                ▼
    ┌─── Harness.before_call(name, args) ───────────────────────────┐
    │                                                                │
    │   ① 路径白名单检查（loadFile / exportData）                    │
    │      args.file_path 在白名单目录内？                           │
    │      ├─ 否 → return {"error": "path not in whitelist"}        │
    │      └─ 是 → 继续                                             │
    │                                                                │
    │   ② 文件大小检查（loadFile）                                   │
    │      文件 < 50MB（可配置）？                                    │
    │      ├─ 否 → return {"error": "file too large"}               │
    │      └─ 是 → 继续                                             │
    │                                                                │
    │   ③ AI Coding 确认检查（run_bash / runPythonString）           │
    │      session.user_confirmed_coding == True？                   │
    │      ├─ 否 → return {"error": "需要用户确认"}                  │
    │      └─ 是 → 继续                                             │
    │                                                                │
    │   ④ 危险命令拦截（run_bash）                                   │
    │      command 包含 rm -rf / sudo / shutdown？                   │
    │      ├─ 是 → return {"error": "dangerous command blocked"}    │
    │      └─ 否 → 继续                                             │
    │                                                                │
    │   return None（允许执行）                                       │
    └────────────────────────────────────────────────────────────────┘
                │
                ▼
        MCP Client.call_tool(name, args)
        → MCP 端点（薄壳）→ PostEngine 执行 → 返回 result: dict
                │
                ▼
    ┌─── Harness.after_call(name, result) ──────────────────────────┐
    │                                                                │
    │   ⑤ 返回值截断（所有 tool）                                    │
    │      json.dumps(result) 长度 > N 字符（如 5000）？             │
    │      ├─ 是 → 保留 summary，截断 data 字段                     │
    │      └─ 否 → 原样返回                                         │
    │                                                                │
    │   ⑥ 计算超时检测                                               │
    │      执行时间 > 60s？                                          │
    │      ├─ 是 → 已被 timeout 终止，返回 error                    │
    │      └─ 否 → 返回结果                                         │
    │                                                                │
    │   return processed_result                                      │
    └────────────────────────────────────────────────────────────────┘
                │
                ▼
        追加到 messages: { role: "tool", content: result }
        → 进入下一轮 LLM 调用
```

---

### 5.7 算法执行路径对比：轻型 vs 重型

```
┌─────────────────────────────────────────────────────────────────┐
│  轻型算法（statistics）                                          │
│                                                                  │
│  MCP 端点 → engine.calculate("statistics", zone="wall")         │
│      │                                                           │
│      ▼  PostEngine 内部                                          │
│  METHODS["statistics"].execute(post_data, params, "wall")       │
│      │                                                           │
│      ▼                                                           │
│  post_data.get_scalar("wall", "pressure")                       │
│      │                                                           │
│      ├── _resolve_name: "pressure" → 映射表 → "Static_Pressure" │
│      ├── vtk_to_numpy(vtkArray) → np.ndarray（零拷贝）          │
│      └── arr.flags.writeable = False                            │
│      │                                                           │
│      ▼                                                           │
│  numpy 计算: np.min(), np.max(), np.mean(), np.std()            │
│      │                                                           │
│      ▼  数据不离开 Python 层，不调 VTK Filter                    │
│  return {                                                        │
│    "type": "numerical",                                          │
│    "summary": "wall压力: min=95000Pa, max=120000Pa, mean=101325Pa",│
│    "data": {"min": 95000, "max": 120000, "mean": 101325, ...},  │
│    "output_files": []                                            │
│  }                                                               │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  重型算法（force_moment）                                        │
│                                                                  │
│  MCP 端点 → engine.calculate("force_moment", zone="wall", ...)  │
│      │                                                           │
│      ▼  PostEngine 内部                                          │
│  METHODS["force_moment"].execute(post_data, params, "wall")     │
│      │                                                           │
│      ▼                                                           │
│  post_data.get_vtk_data() → vtkMultiBlockDataSet                │
│      │                                                           │
│      ▼  直接操作 VTK 对象（需要面元法向量、面积、单元拓扑）       │
│  ForceMomentIntegtal (C++ 模块)                                  │
│      ├── 设置参数: density, velocity, refArea, alpha_angle...    │
│      ├── 设置数据: vtkDataSet (wall block)                       │
│      ├── Execute() → C++ 层面元积分                               │
│      └── GetOutput() → force{x,y,z}, moment{x,y,z}, coeff{CL,CD}│
│      │                                                           │
│      ▼  C++ 计算完成，结果回到 Python                             │
│  return {                                                        │
│    "type": "numerical",                                          │
│    "summary": "wall: Fx=123.4N, CL=0.35, CD=0.012",            │
│    "data": {"force":{...}, "moment":{...}, "coefficients":{...}},│
│    "output_files": []                                            │
│  }                                                               │
└─────────────────────────────────────────────────────────────────┘
```

---

### 5.8 子 Agent 交互模型（Phase 3）

**核心问题**：LLM 上下文窗口是有限资源。某些操作会向上下文注入大量数据，挤压后续对话空间。

| 操作 | 上下文膨胀量 | 影响 |
|------|:----------:|------|
| 加载一个文件的 summary | ~500 tokens | 可控 |
| 同时加载两个文件做对比 | ~1000+ tokens | 开始吃紧 |
| AI Coding 脚本 + 执行输出 | ~2000-5000 tokens | 严重挤占后续对话 |
| 多步分析生成报告（5-10 步） | ~3000-8000 tokens | 可能触发上下文压缩 |

**子 Agent 解决方式**：上下文隔离 + 只返回摘要。

```
┌─────────────────────────────────────────────────────────────────────┐
│  主 Agent（常驻，和用户直接对话）                                      │
│                                                                      │
│  AgentSession.messages = [完整对话历史]                               │
│                                                                      │
│  判断：需要隔离？                                                     │
│  ├─ 否（绝大多数场景）→ 自己调 MCP tool 处理                          │
│  └─ 是（仅 3 种场景）→ 创建子 Agent                                  │
│                              │                                       │
│       ┌──────────────────────┼──────────────────────┐               │
│       ▼                      ▼                      ▼               │
│  ┌──────────────┐  ┌──────────────────┐  ┌──────────────────┐      │
│  │ 对比子 Agent  │  │ Coding 子 Agent  │  │  报告子 Agent     │      │
│  │              │  │                  │  │                  │      │
│  │ messages=[   │  │ messages=[       │  │ messages=[       │      │
│  │  task_desc   │  │  task_desc       │  │  task_desc       │      │
│  │ ] ← 干净     │  │ ] ← 干净         │  │ ] ← 干净         │      │
│  │              │  │                  │  │                  │      │
│  │ 独立调 LLM   │  │ 独立调 LLM       │  │ 独立调 LLM       │      │
│  │ 共享 MCP     │  │ 共享 MCP         │  │ 共享 MCP         │      │
│  │ 共享 Session │  │ 需用户确认 ←──┐  │  │ 共享 Session     │      │
│  │              │  │               │  │  │                  │      │
│  │ 返回:摘要    │  │ 返回:摘要     │  │  │ 返回:摘要+文件   │      │
│  │ 然后销毁     │  │ 然后销毁      │  │  │ 然后销毁         │      │
│  └──────┬───────┘  └──────┬────────┘  │  └──────┬───────────┘      │
│         │                  │  Harness层 │         │                  │
│         │                  │  确认拦截───┘         │                  │
│         ▼                  ▼                      ▼                  │
│  主 Agent 收到 ~50 tokens 摘要（而不是 5000 tokens 中间过程）         │
│  组装回复 → WS → 前端                                                │
└─────────────────────────────────────────────────────────────────────┘
```

**三种子 Agent 的数据流详解：**

**场景 1：多文件对比**
```
用户："对比 ysy.cgns 和 abc.cgns 的压力"

主 Agent                          对比子 Agent（干净上下文）
  │                                    │
  ├─ 判断：涉及两个文件                 │
  ├─ 创建子 Agent ───────────────────→ │ messages = [task_desc]
  │  task: "加载 ysy.cgns 和           │
  │   abc.cgns，对比 wall:Pressure"    │
  │                                    ├─ loadFile("ysy.cgns") → MCP → PostEngine
  │                                    │  SessionState.post_data = ysy
  │                                    ├─ 取 wall:Pressure 统计
  │                                    ├─ loadFile("abc.cgns") → MCP → PostEngine
  │                                    │  SessionState.post_data = abc（覆盖缓存）
  │                                    ├─ 取 wall:Pressure 统计
  │                                    ├─ compare(...)
  │                                    ├─ 返回摘要 ←─────────────────┐
  │  ←──── 摘要（~50 tokens）──────────┤  "最大差异 12.3%，均值差异 2.1%"
  │                                    └─ 销毁
  ├─ 恢复原 SessionState（ysy）
  └─ 回复用户
```

**场景 2：AI Coding（需用户确认）**
```
用户："画 wall 沿 x 方向的 Cp 分布"

主 Agent                          Coding 子 Agent（干净上下文）
  │                                    │
  ├─ 判断：没有 plot method             │
  ├─ 先问用户（不创建子 Agent）         │
  │  "需要编写 Python 脚本，是否允许？"  │
  │                                    │
用户："可以"                            │
  │                                    │
  ├─ session.user_confirmed_coding=True │
  ├─ 创建子 Agent ───────────────────→ │ messages = [task_desc]
  │  task: "提取 wall 的坐标和 Cp，     │
  │   用 matplotlib 生成分布曲线"       │
  │                                    ├─ 通过 MCP 取数据
  │                                    │  get_scalar("wall","cp")
  │                                    ├─ 编写 matplotlib 脚本
  │                                    ├─ run_bash(脚本)
  │                                    │  → Harness 检查 confirmed=True ✓
  │                                    ├─ 执行输出留在子 Agent 上下文
  │                                    │  （不回到主对话，省 token）
  │  ←──── 摘要 + 文件路径 ────────────┤  "已生成，保存到 cp_plot.png"
  │                                    └─ 销毁
  ├─ 推送到 Artifact（前端展示图片）
  └─ 回复用户
```

**场景 3：完整报告生成**
```
用户："给我一份 ysy.cgns 的完整分析报告"

主 Agent                          报告子 Agent（干净上下文）
  │                                    │
  ├─ 判断：多步分析，中间数据量大       │
  ├─ 创建子 Agent ───────────────────→ │ messages = [task_desc]
  │  task: "对 ysy.cgns 完整分析：      │
  │   概要、统计、力矩、关键发现"       │
  │                                    ├─ loadFile("ysy.cgns") → 概要
  │                                    ├─ calculate("statistics") → 统计
  │                                    ├─ calculate("force_moment") → 力矩
  │                                    ├─ 综合分析，生成报告
  │                                    │  （~5000 tokens 中间过程）
  │  ←──── 摘要 + 报告文件 ────────────┤  "3区域，CL=0.35，马赫异常高"
  │                                    └─ 销毁（5000 tokens 丢弃）
  ├─ 主 Agent 只收到 ~80 tokens
  ├─ 推送报告到 Artifact
  └─ 回复用户
```

**子 Agent 约束规则：**

| 规则 | 说明 |
|------|------|
| 共享 MCP 连接 | 不为子 Agent 建独立 SSE 连接，复用主 Agent 的 |
| 共享 SessionState | 主 Agent 已加载的文件，子 Agent 直接用 |
| 不直接和用户对话 | 子 Agent 只通过主 Agent 中转 |
| 完成即销毁 | 中间过程不保留，只保留摘要 |
| SessionState 竞争 | 对比子 Agent 可能覆盖缓存，执行完需恢复 |
| Phase 1-2 不实现 | 全部由主 Agent 直接处理，Phase 3 再引入 |

**子 Agent 的自研实现要点（~80 行）：**

```python
class SubAgent:
    """干净上下文 + 独立 LLM 调用 + 共享 MCP 连接"""

    def __init__(self, task_desc: str, mcp_client: MCPClient, system_prompt: str):
        self.messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task_desc},
        ]
        self.mcp_client = mcp_client       # 复用主 Agent 的连接

    async def run(self) -> str:
        """独立执行，返回摘要字符串"""
        while True:
            response = await litellm.acompletion(
                model=MODEL,
                messages=self.messages,
                tools=self.mcp_client.get_tools_for_llm(),
            )
            msg = response.choices[0].message
            self.messages.append(msg.model_dump())

            if not msg.tool_calls:
                return msg.content           # 最终文本 = 摘要

            for tc in msg.tool_calls:
                result = await self.mcp_client.call_tool(tc.function.name, tc.function.arguments)
                self.messages.append({"role": "tool", "tool_call_id": tc.id, "content": str(result)})
        # 方法返回后，self 被丢弃 → 中间 messages 全部释放

# 主 Agent 中调用：
sub = SubAgent(task_desc="对比 ysy.cgns 和 abc.cgns ...", mcp_client=session.mcp_client, ...)
summary = await sub.run()    # 子 Agent 执行完，只拿到摘要
# sub 离开作用域 → GC 回收 → 中间 messages 释放
```

---

### 5.9 AI Coding 完整流程

AI Coding 横跨 Agent 层多个模块，是 Harness、子 Agent、前端 Artifact 的交叉点。

```
用户："帮我画一个壁面压力分布曲线"

┌─ Agent Loop ──────────────────────────────────────────────────────┐
│                                                                    │
│  1. LLM 判断：当前工具没有绘图功能，需要写代码                       │
│     （Skill 层引导："没有对应 method 时，提出 AI Coding 方案"）       │
│                                                                    │
│  2. AI 回复用户（不执行代码）：                                      │
│     "我可以编写 Python 脚本来：                                      │
│      1) 提取 wall 区域的坐标和压力数据                               │
│      2) 用 matplotlib 生成压力分布曲线                               │
│      是否允许执行？"                                                 │
│                       │                                             │
│                       ▼ WS → 前端展示 → 用户看到                     │
│                                                                    │
│  3. 用户回复："可以"                                                 │
│                       │                                             │
│                       ▼                                             │
│  4. Agent 设置确认标记：                                             │
│     session.user_confirmed_coding = True                            │
│                                                                    │
│  5. Phase 1-2：主 Agent 直接执行                                    │
│     │  LLM 生成脚本 → tool_call: run_bash(script)                  │
│     │      │                                                        │
│     │      ▼                                                        │
│     │  Harness.before_call("run_bash", args):                      │
│     │      ├─ check_coding_confirm() → confirmed=True ✓            │
│     │      ├─ check_command_blacklist() → 无危险命令 ✓              │
│     │      ├─ check_script_length() → < 2000 字符 ✓                │
│     │      └─ 通过                                                  │
│     │      │                                                        │
│     │      ▼ 执行（60s 超时）                                       │
│     │  输出 → Harness.after_call() → 截断（> 5000 字符）            │
│     │  → Agent 回复用户 + 推送文件到 Artifact                       │
│     │                                                               │
│     Phase 3：创建 Coding 子 Agent 隔离执行                          │
│     │  SubAgent(task_desc, mcp_client)                              │
│     │      子 Agent 内部执行脚本，中间输出留在子 Agent 上下文        │
│     │      → 返回摘要 + 文件路径                                    │
│     │  → Agent 回复用户 + 推送文件到 Artifact                       │
│                                                                    │
│  6. 重置确认标记：                                                  │
│     session.user_confirmed_coding = False                           │
│     （每次 Coding 任务完成后重置，下次需重新确认）                    │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

**AI Coding 安全约束（全在 Harness 层）：**

| 约束 | 检查时机 | 拦截方式 |
|------|---------|---------|
| 执行前必须用户确认 | before_call | `user_confirmed_coding == False` → 拒绝 |
| 脚本长度限制 | before_call | `len(script) > 2000` → 拒绝 |
| 危险命令拦截 | before_call | `rm/sudo/shutdown` → 拒绝 |
| 执行超时 | 执行层 | 60s 强制终止 |
| 输出截断 | after_call | `len(output) > 5000` → 截断 |

---

### 5.10 Agent 决策流程（反问确认机制）

Agent Loop 中 LLM 不是随意选 tool 的，Skill 层引导了一套决策优先级：

```
用户输入
  │
  ▼
匹配 Skill 固化工作流？（System Prompt 中的 6 种模式）
  ├── "提到文件名"      → loadFile → 返回概要
  ├── "说力/CL/CD"      → calculate("force_moment")
  ├── "说涡量/马赫/Cp"  → calculate("velocity_gradient")
  ├── "说提取/导出/CSV" → exportData
  ├── "说对比/比较"     → compare
  ├── "说参数/怎么用"   → getMethodTemplate
  │
  └── 未匹配 Skill ↓
      │
      ▼
  匹配 calculate 的某个 method？
  （LLM 结合 getMethodTemplate 返回的算法列表判断）
      ├── 是 → calculate(method=...) → 执行
      └── 否 ↓
          │
          ▼
      可以通过 exportData 解决？
          ├── 是 → exportData → 执行
          └── 否 ↓
              │
              ▼
          需要写代码才能解决？
              ├── 是 → 描述方案，请求确认（AI Coding 流程）
              │        不直接执行，等用户说"可以"
              └── 否 ↓
                  │
                  ▼
              超出能力范围
              → 告诉用户当前支持什么
              → 建议替代方案
              → Insight Log 记录 resolution="unresolved"
```

**反问模板（Prompt 软约束）：**

| 场景 | AI 的反问 |
|------|----------|
| 意图模糊 | "您想分析哪个方面？1) 文件概要 2) 力和力矩 3) 提取数据" |
| 参数缺失 | "计算力矩需要：来流密度(kg/m³)、来流速度(m/s)、参考面积(m²)" |
| 算法不存在 | "当前没有'压力云图'功能。我可以：1) 提取压力到 CSV 2) 写脚本生成图表（需确认）" |
| 区域不确定 | "该文件包含 3 个区域：solid、far、wall。您想分析哪个？" |
| 文件未加载 | "请先告诉我要分析的文件路径" |

---

### 5.11 前端内部组成

```
web/                               # Vue.js + VTK.js 前端
├── src/
│   ├── App.vue                    # 主布局：左侧对话 + 右侧 Artifact
│   │
│   ├── components/
│   │   ├── ChatPanel/             # 对话区域
│   │   │   ├── ChatPanel.vue      # 对话面板容器
│   │   │   ├── MessageList.vue    # 消息列表（用户 + AI）
│   │   │   ├── MessageInput.vue   # 输入框 + 发送按钮
│   │   │   └── FileUpload.vue     # 文件上传组件
│   │   │
│   │   ├── ArtifactPanel/         # Artifact 侧边栏
│   │   │   ├── ArtifactPanel.vue  # 侧边栏容器
│   │   │   ├── ArtifactList.vue   # Artifact 列表（点击切换）
│   │   │   ├── JsonCard.vue       # JSON 结果卡片（力矩等）
│   │   │   ├── DataTable.vue      # 数据表格（CSV）
│   │   │   ├── ImageViewer.vue    # 图片查看（AI Coding 生成的 PNG）
│   │   │   └── FileSummary.vue    # 文件概要卡片（区域/标量列表）
│   │   │
│   │   └── VtkViewer/             # VTK.js 3D 渲染
│   │       ├── VtkViewer.vue      # 3D 视窗容器
│   │       ├── MeshRenderer.js    # 网格渲染（几何 + 标量着色）
│   │       └── ViewControls.js    # 交互控制（旋转/缩放/平移）
│   │
│   ├── services/
│   │   ├── websocket.js           # WebSocket 连接管理
│   │   │   ├── connect(session_id)     → 建立 WS 连接
│   │   │   ├── send(message)           → 发送用户消息
│   │   │   ├── onMessage(callback)     → 接收 AI 回复 + Artifact 推送
│   │   │   └── onStream(callback)      → 接收流式输出
│   │   │
│   │   └── api.js                 # HTTP API 客户端（直连后处理服务）
│   │       ├── getMesh(session, zone)        → GET /api/mesh/...
│   │       ├── getScalar(session, zone, name) → GET /api/scalar/...
│   │       ├── downloadFile(path)            → GET /api/file/...
│   │       └── uploadFile(file)              → POST /api/upload
│   │
│   └── store/                     # 状态管理
│       ├── chat.js                # 对话历史状态
│       └── artifacts.js           # Artifact 列表状态
```

**前端布局：**

```
┌──────────────────────────────────┬────────────────────────────┐
│         对话区域                  │       Artifact 区域         │
│                                  │                            │
│  用户: 分析 ysy.cgns             │   ┌────────────────────┐   │
│                                  │   │                    │   │
│  AI: 文件已加载                  │   │  当前查看的内容      │   │
│      3个区域: solid/far/wall     │   │  （3D / 表格 / 图表）│   │
│      [📎 文件概要]               │   │                    │   │
│                                  │   └────────────────────┘   │
│  用户: 算力矩                    │                            │
│                                  │   ── Artifacts ──────────  │
│  AI: CL=0.35, CD=0.012          │   文件概要           [👁]  │
│      [📎 力矩结果]               │   力矩结果           [👁]  │
│                                  │   wall 压力云图       [👁]  │
│                                  │   wall 压力.csv       [👁]  │
└──────────────────────────────────┴────────────────────────────┘
```

**前端双通道数据流：**

```
                           ┌───────────────┐
                           │   Agent 服务   │
                      ┌────┤               ├────┐
                      │ WS │               │    │
                      │    └───────────────┘    │
                      │                         │
                      ▼                         │
         ┌────────────────────┐                 │
         │  对话通道           │                 │
         │  ① 发送用户消息    │                 │
         │  ⑦ 接收 AI 回复   │                 │
         │  ⑦ 接收 Artifact  │                 │
         │    推送通知        │                 │
         └────────────────────┘                 │
                                                │
                           ┌───────────────┐    │
                           │   后处理服务   │    │
                      ┌────┤   HTTP API    ├────┘
                      │HTTP│               │
                      │    └───────────────┘
                      ▼
         ┌────────────────────┐
         │  数据通道           │
         │  ⑧ 请求网格几何    │   前端收到 Artifact 通知后
         │  ⑧ 请求标量数组    │   主动通过 HTTP API 拉取大数据
         │  ⑧ 下载导出文件    │   不经过 Agent/LLM
         └────────────────────┘
```

**Artifact 数据类型与查看方式：**

| 数据类型 | 来源 | 默认查看方式 | 数据通道 |
|---------|------|------------|---------|
| 网格数据 (.vtm) | loadFile | VTK.js 3D 渲染 | HTTP API（大数据） |
| 数值结果 (JSON) | calculate | 格式化卡片 | WS（小数据，在 summary 里） |
| 表格数据 (.csv) | exportData | 数据表格 | HTTP API（下载文件） |
| 图片 (.png) | AI Coding | 图片查看 | HTTP API（下载文件） |
| 文件概要 | loadFile | 区域/标量概览卡片 | WS（小数据，在 summary 里） |

---

### 5.12 分析存档（Analysis Archive）

存档不是 AI Memory，是用户的工程文档。AI 不自动写入，只在用户明确要求时才保存。

```
存储位置：数据文件所在目录下的 .chatcfd/ 子目录

D:/XField/data/cgns/               ← 用户数据目录
├── ysy.cgns                       ← 数据文件
└── .chatcfd/                      ← 存档目录（首次保存时创建）
    └── ysy.cgns.archive.json      ← 该文件的分析存档
```

**存档在系统中的位置：**

```
用户说"保存这次结果"
  │
  ▼
Agent Loop → LLM 判断意图 → 调用 MCP tool
  │
  ▼
PostEngine:
  ├── 取当前 SessionState 中的最近计算结果
  ├── 写入 .chatcfd/ysy.cgns.archive.json
  │   {
  │     file: "ysy.cgns",
  │     file_md5: "a1b2c3...",      ← 校验文件是否被修改
  │     entries: [
  │       { timestamp, method, zone, params, result, note }
  │     ]
  │   }
  └── 返回确认

下次 loadFile("ysy.cgns") 时:
  ├── PostEngine 检查 .chatcfd/ysy.cgns.archive.json 是否存在
  ├── 比对 md5
  │   ├── 匹配 → summary 中提示"该文件有历史分析记录"
  │   └── 不匹配 → 提示"文件已更新，历史存档可能不适用"
  └── LLM 看到提示 → 告知用户
```

---

### 5.13 约束三层协作完整示例

用户说："算一下 ysy.cgns 的升力系数"

```
┌─ ① Harness 层（代码强制，AI 无法绕过）──────────────────────────────┐
│                                                                      │
│  before_call("loadFile", {file_path: "ysy.cgns"}):                  │
│    ✓ 路径白名单检查通过                                               │
│    ✓ 文件大小检查通过                                                 │
│                                                                      │
│  before_call("calculate", {method: "force_moment"}):                │
│    ✓ 非 run_bash，不需要 Coding 确认                                  │
│                                                                      │
│  after_call → 返回值截断检查                                          │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
                │ 通过
                ▼
┌─ ② Skill 层（固化工作流，AI 看到就按步骤走）────────────────────────┐
│                                                                      │
│  System Prompt 中的 Skill 定义：                                      │
│    "用户说力/升力/CL/CD → 确认文件已加载 → calculate(force_moment)"  │
│                                                                      │
│  LLM 看到这条 Skill → 按流程走：                                     │
│    1. 检查文件是否已加载 → 未加载 → 先调 loadFile("ysy.cgns")        │
│    2. 调 calculate(method="force_moment")                            │
│    3. 从结果 summary 中取 lift_coefficient                           │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
                │ 执行完
                ▼
┌─ ③ Prompt 层（行为规范，AI 大部分时候遵守）─────────────────────────┐
│                                                                      │
│  Prompt 约束生效：                                                    │
│    ✓ 发现用户没给参考面积和来流条件                                    │
│      → "先确认"规则触发 → 先反问用户要参考条件                         │
│    ✓ 拿到结果后简短展示                                               │
│      → "简洁"规则：回复"升力系数 CL = 0.35"                          │
│      → 不把完整的 force/moment JSON 全部输出                          │
│    ✓ 单位规范                                                         │
│      → "力的单位是 N"                                                 │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
                │
                ▼
            Insight Log 记录：
            resolution = "skill_matched"（Skill 直接命中）
```

---

### 5.14 Insight Log 记录结构

每次用户提问自动记录一条，由 Agent 层写入（不依赖 PostEngine）。

```json
{
  "timestamp": "2026-04-03T10:30:00",
  "session_id": "abc123",
  "user_input": "帮我画一个壁面的压力分布曲线",
  "resolved": false,
  "resolution": "fallback_coding",
  "tools_called": ["loadFile", "getMethodTemplate"],
  "final_tool": "run_bash",
  "tags": ["visualization", "pressure", "wall"],
  "notes": "用户想要绘图，当前无绘图 method，降级为 AI Coding"
}
```

**resolution 分类与产品迭代闭环：**

```
用户提问 → Agent 处理 → Insight Log 记录 resolution
                                    │
                            定期聚合统计
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
             skill_matched     fallback_coding   unresolved
             （理想状态）      （能力不够写代码）  （完全做不了）
                                    │               │
                                    ▼               ▼
                            高频 → 新增 method   高频 → 新增算法/功能
                                    │               │
                                    ▼               ▼
                            下次同样问题 → skill_matched
```

---

### 5.15 依赖清单

| 模块 | 依赖 | 用途 | 是否必须 |
|------|------|------|:-------:|
| **Agent 服务层** | | | |
| main.py | `fastapi`, `uvicorn` | WebSocket + HTTP 服务 | 是 |
| agent_loop.py | `litellm` | 统一多 LLM 调用 | 是 |
| mcp_client.py | `mcp` (官方 SDK) | MCP SSE 客户端 | 是 |
| harness.py | 标准库 | 拦截逻辑 | 是 |
| insight_log.py | 标准库 (`json`) | JSONL 写入 | 是 |
| **后处理服务** | | | |
| server.py | `fastmcp`, `fastapi` | MCP Server + HTTP API | 是 |
| post_data.py | `numpy`, `vtk` | 薄封装 + 零拷贝 | 是 |
| algorithms/*.py | `numpy` / `vtk` | 按算法而定 | 是 |
| vtk_layer/ | `vtk` 9.4.1 + 自研 C++ | IO + Filters | 是 |
| **前端** | | | |
| web/ | `vue`, `vtk.js` | 对话 + 3D 渲染 | 是 |

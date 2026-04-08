# Mempalace 集成方案

> 日期：2026-04-08
> 状态：设计评审完成，待实施
> 依赖：Mempalace (D:/Git/GitBubProj/Mempalace)

## 1. 目标

为 chatCFD 引入跨会话记忆能力，让 AI 助手记住用户的分析偏好、工程发现和历史结论，从"无状态工具"进化为"有经验的分析助手"。

## 2. 与现有 Analysis Archive 的边界

PRD §14 已规划 Analysis Archive（结构化、按文件索引、md5 校验）。两者职责不同，不替代：

| 维度 | Analysis Archive | Mempalace |
|------|-----------------|-----------|
| 存什么 | 精确计算结果 + 参数 | 模糊偏好 / 工程发现 / 工作流模式 |
| 索引方式 | 按文件路径 + md5 | 按 wing/room + 语义搜索 |
| 触发 | 用户主动说"保存" | LLM 判断是否值得记忆 |
| 存储位置 | `.chatcfd/`（跟着数据文件走） | `~/.mempalace/`（全局） |
| 跨文件搜索 | 不支持 | 支持 |
| 数据一致性 | md5 校验 | 无（依赖记忆时效性判断） |

**System prompt 中须明确**：用户说"保存结果" → Archive；AI 主动沉淀偏好/发现 → Mempalace。

## 3. 架构方案

### 3.1 接入方式：MCPClientPool（多 server + 多协议）

当前 `agent/mcp_client.py` 是 SSE-only 单 server。改为 MCPClientPool：

```
MCPClientPool
├── "post_service" → SSE client (http://127.0.0.1:8000/mcp/sse)
└── "mempalace"    → stdio client (python -m mempalace.mcp_server)
```

- tool 按名称路由（mempalace_ 前缀自然区分）
- mcp SDK 本身同时支持 sse_client 和 stdio_client

### 3.2 工具暴露策略：只暴露 4 个给 LLM

chatCFD 6 个 + Mempalace 21 个 = 27 个工具。全部暴露会严重降低 LLM 工具选择准确率（建议 ≤15 个）。

**暴露给 LLM（4 个）**：

| 工具 | 用途 |
|------|------|
| `mempalace_search` | 查询记忆（用户说"上次/之前"时） |
| `mempalace_add_drawer` | 存储记忆（分析得出重要结论时） |
| `mempalace_kg_query` | 查询用户偏好（参照系、常用参数等） |
| `mempalace_kg_add` | 存储用户偏好变更 |

**代码层自动调用（不暴露）**：

| 工具 | 调用时机 |
|------|---------|
| `mempalace_status` | 服务启动时检查 palace 状态 |
| `mempalace_check_duplicate` | add_drawer 前自动去重 |
| `mempalace_list_wings/rooms` | 内部 wing/room 推断 |
| `mempalace_kg_invalidate` | 偏好覆盖时自动失效旧三元组 |
| `mempalace_diary_*` | Phase 3 子 Agent 内部使用 |
| `mempalace_traverse/tunnels/graph_stats` | 不暴露 |
| `mempalace_get_aaak_spec` | 不使用 AAAK（有损压缩，不适合 CFD 精确数值） |
| `mempalace_delete_drawer` | 不暴露（防 LLM 误删） |
| `mempalace_get_taxonomy` | 内部使用 |

合并后 LLM 看到 **6 + 4 = 10 个工具**，在安全范围内。

### 3.3 记忆注入时机

**不在对话开始时盲目注入**（此时 wing 未知，可能注入不相关记忆）。

| 时机 | 注入内容 | 实现方式 |
|------|---------|---------|
| 对话开始 | 仅全局偏好（参照系、单位等） | `mempalace_kg_query(entity="user")` |
| loadFile 之后 | 该项目的历史发现和结论 | `mempalace_search(wing=推断的wing)` |
| 用户说"上次/之前/记得吗" | 按查询语义检索 | LLM 主动调 `mempalace_search` |
| calculate 返回结果后 | LLM 判断是否存入 | LLM 主动调 `mempalace_add_drawer` |
| 用户偏好变更 | 更新知识图谱 | LLM 主动调 `mempalace_kg_add` |

### 3.4 记忆架构：Wing / Room / Hall

**Wing = 项目级别**（用户命名或从文件路径推断，预期 <20 个）

```
命名规则：文件路径取项目级目录
  D:/XField/NACA0012/case_001.cgns → wing: "naca0012"
  D:/XField/WindTunnel/run_023.cgns → wing: "windtunnel"
```

**Room = LLM 存储时从预定义列表选择**（不用关键词自动检测，对话场景不适用）

初始 Room 种子（开放集，可自然扩展）：

| Room | 存什么 | 举例 |
|------|-------|------|
| results | 数值结论 | "升力系数 CL=0.45, 阻力系数 CD=0.021" |
| parameters | 常用参数 | "参考面积 1.0, 来流密度 1.225" |
| visualization | 可视化偏好 | "涡量等值面阈值 mean+2std, 常用切面 x=0.3" |
| findings | 工程发现 | "翼尖处存在明显分离区" |
| workflow | 工作流模式 | "用户习惯先看力矩再看涡量分布" |

新学科（结构/热/声学）扩展时增加新 room 即可，不改框架。

**Hall = 沿用 Mempalace 原有 5 个**，不修改。

**知识图谱 = 仅用于有时序性的关系**：

```
适合 KG：
  (user, prefers_reference_frame, body)  valid_from=2026-03  valid_to=2026-04
  (user, prefers_reference_frame, wind)  valid_from=2026-04
  (case_A, compared_with, case_B)        valid_from=2026-04-08

不适合 KG（用 drawer）：
  "case_run023 在 wall 区域 CL=0.45" → drawer in results room
```

## 4. Embedding 模型策略

### 4.1 问题

Mempalace 默认使用 all-MiniLM-L6-v2（英文模型），对中文 CFD 术语检索失效。

### 4.2 三层挑战与应对

| 挑战层 | 问题 | 方案 | 优先级 |
|--------|------|------|--------|
| 语言层 | 纯英文模型无法理解中文 | 换 `bge-small-zh-v1.5`（96MB，nDCG@10=63） | P1 |
| 术语映射层 | "升力系数" vs "CL" 词汇鸿沟 | 存储规范：中英文双写（system prompt 规则） | P0 |
| 精确匹配层 | 数值 "0.45" 无语义权重 | 依赖 wing/room 元数据过滤缩小候选集 | P0 |

### 4.3 存储规范（写入 system prompt）

```
存入记忆时，物理量必须用「中文全称 + 英文缩写 + 数值」格式：
  好: "升力系数 CL=0.45, 阻力系数 CD=0.021, body 参照系"
  差: "CL=0.45, CD=0.021"
```

### 4.4 Embedding 替换

在 Mempalace 初始化时指定自定义 embedding function：

```python
from chromadb import EmbeddingFunction
from sentence_transformers import SentenceTransformer

class CFDEmbedding(EmbeddingFunction):
    def __init__(self):
        self.model = SentenceTransformer("BAAI/bge-small-zh-v1.5")
    def __call__(self, input):
        return self.model.encode(input, normalize_embeddings=True).tolist()
```

注意：必须在初始集成时就替换，不能先用默认模型再换（需重新 embed 全部 drawer）。

### 4.5 不采用的方案

| 方案 | 不采用原因 |
|------|-----------|
| bge-m3 | 2.2GB 太重，chatCFD 是后处理工具不是 RAG 系统 |
| SciBERT | 不支持中文 |
| BM25 混合检索 | Mempalace 数据显示关键词加权仅提升 1.8%，投入产出比差 |
| all-mpnet-base-v2 | 英文模型，不解决中文问题 |

## 5. 需要修改的 chatCFD 模块

| 模块 | 改动 | 复杂度 |
|------|------|--------|
| `agent/mcp_client.py` | 重构为 MCPClientPool，支持 SSE + stdio 双协议 | 中 |
| `agent/agent_loop.py` | tool dispatch 支持多 server 路由；loadFile 后触发记忆检索 | 中 |
| `agent/session.py` | AgentSession 增加 memory_wing / loaded_file_path | 低 |
| `agent/skills.py` | system prompt 增加记忆工具使用规则 + 存储规范 | 低 |
| `agent/harness.py` | mempalace_delete_drawer 加确认拦截 | 低 |
| `agent/main.py` | 启动时初始化 mempalace stdio client | 低 |

## 6. 不修改 Mempalace 框架本身

| 方面 | 说明 |
|------|------|
| MCP 协议 | 保持 stdio，chatCFD 侧适配 |
| Wing/Room/Hall | 动态创建，不改代码 |
| 知识图谱 | 三元组 + 时序足够 |
| AAAK 方言 | 不使用（有损压缩，CFD 需要精确数值） |
| 配置 | 仅 config 级别调整 topic_wings |

唯一需要的是在 Mempalace 的 ChromaDB 初始化处**注入自定义 embedding function**（bge-small-zh），可通过配置或 monkey-patch 实现，不改 Mempalace 源码。

## 7. 专家 Agent 决策

### 7.1 当前不新增专家 Agent

理由：
- chatCFD 的 6 个工具不支撑专业分工（"专家"只是同一套工具的不同调用方式）
- 一个有记忆的主 Agent > 四个无记忆的专家 Agent
- PRD 的子 Agent（对比/Coding/报告）动机是上下文隔离，不是专业分工

### 7.2 PRD 已规划的 3 个子 Agent + diary

Phase 3 实施子 Agent 时，为 Coding 子 Agent 接入 Mempalace diary：
- `mempalace_diary_write("coding_agent", "用户要求画 Cp 分布，用了 matplotlib + 提取 wall 的 x 坐标和 Cp")`
- `mempalace_diary_read("coding_agent")` → 下次类似需求直接复用脚本模式

### 7.3 未来专家 Agent 条件

当 chatCFD 从"后处理工具"扩展为"仿真分析平台"时，以下方向值得做独立专家：

| 专家 | 前提条件 | 独立知识体系 |
|------|---------|------------|
| 结果解读专家 | 支持物理合理性判断 API | 典型流态的正常值范围、异常检测模式 |
| 验证对标专家 | 支持多案例批量处理 + 实验数据导入 | GCI 分析、Richardson 外推、不确定度 |

判断标准：① 知识超出 system prompt 容量 ② 记忆与主 Agent 不同维度 ③ 需要独立 LLM 上下文

## 8. 实施阶段

### Phase M1（最小可用 — 记忆增强主 Agent）

- MCPClientPool 多 server 支持
- bge-small-zh embedding 替换
- 4 个 mempalace 工具暴露给 LLM
- system prompt 增加记忆规则 + 存储规范
- loadFile 后触发记忆检索

### Phase M2（智能记忆）

- 自动 wing 推断（loadFile 路径 → wing 名）
- LLM 选择 room 归属
- 知识图谱存储用户偏好变迁
- 对话结束时 LLM 判断是否沉淀关键结论

### Phase M3（子 Agent + diary）

- Coding 子 Agent 接入 diary
- 报告子 Agent 接入 diary（记住报告模板偏好）

# ChatCFD 产品需求文档 (PRD)

## 目录

- [1. 产品概述](#1-产品概述)
  - [1.1 产品定义](#11-产品定义)
  - [1.2 核心价值](#12-核心价值)
  - [1.3 目标用户](#13-目标用户)
- [2. 系统架构](#2-系统架构)
  - [2.1 整体架构](#21-整体架构)
  - [2.2 数据流](#22-数据流)
  - [2.3 会话与连接模型](#23-会话与连接模型)
  - [2.4 分层职责](#24-分层职责)
  - [2.5 跨层约束对照](#25-跨层约束对照)
- [3. MCP 工具设计](#3-mcp-工具设计)
  - [3.1 设计原则](#31-设计原则)
  - [3.2 工具清单（6 个）](#32-工具清单6-个)
  - [3.3 工具边界](#33-工具边界)
  - [3.4 统一返回格式](#34-统一返回格式)
  - [3.5 calculate 支持的 method](#35-calculate-支持的-method算法注册表)
  - [3.6 compare 工具](#36-compare-工具)
  - [3.7 exportData 工具](#37-exportdata-工具)
- [4. 数据层设计（PostData）](#4-数据层设计postdata)
  - [4.1 目标](#41-目标)
  - [4.2 方案：薄封装（零拷贝访问）](#42-方案薄封装零拷贝访问)
  - [4.3 接口定义](#43-接口定义)
  - [4.4 为什么不复制数据](#44-为什么不复制数据)
  - [4.5 风险与应对](#45-风险与应对)
  - [4.6 VTK 耦合边界](#46-vtk-耦合边界)
  - [4.7 物理量映射表](#47-物理量映射表)
- [5. 会话状态管理](#5-会话状态管理)
- [6. AI 约束分层设计](#6-ai-约束分层设计)
  - [6.1 Harness（硬约束）](#61-harness硬约束--代码层强制执行)
  - [6.2 Skill（中约束）](#62-skill中约束--固化工作流)
  - [6.3 Prompt（软约束）](#63-prompt软约束--行为规范)
  - [6.4 三层协作示例](#64-三层协作示例)
- [7. 现有 C++ 模块清单](#7-现有-c-模块清单)
- [8. 部署方案](#8-部署方案)
- [9. 算法插件化](#9-算法插件化)
  - [9.1 目录结构](#91-目录结构)
  - [9.2 算法文件规范](#92-算法文件规范)
  - [9.3 自动加载机制](#93-自动加载机制)
  - [9.4 新增算法流程](#94-新增算法流程)
- [10. 代码质量规范](#10-代码质量规范)
- [11. 子 Agent 设计](#11-子-agent-设计)
  - [11.0 为什么需要子 Agent](#110-为什么需要子-agent)
  - [11.1 层级结构](#111-层级结构)
  - [11.2 主 Agent 与子 Agent 的边界](#112-主-agent-与子-agent-的边界)
  - [11.3 什么时候用，什么时候不用](#113-什么时候用子-agent什么时候不用)
  - [11.4 约束规则](#114-约束规则)
  - [11.5 交互模式详解](#115-交互模式详解)
- [12. AI Coding 能力](#12-ai-coding-能力)
- [13. 前端 Artifact 设计](#13-前端-artifact-设计)
  - [13.1 布局](#131-布局)
  - [13.2 交互规则](#132-交互规则)
  - [13.3 数据类型与查看方式](#133-数据类型--查看方式)
  - [13.4 对话与 Artifact 联动](#134-对话与-artifact-联动)
  - [13.5 VTK.js 3D 视窗](#135-vtkjs-3d-视窗)
- [14. 分析存档（Analysis Archive）](#14-分析存档analysis-archive)
- [15. 工作流兜底 — 反问确认机制](#15-工作流兜底--反问确认机制)
- [16. 需求洞察日志（Insight Log）](#16-需求洞察日志insight-log)
- [17. 实施路线](#17-实施路线)
- [18. 测试用例](#18-测试用例)

---

## 1. 产品概述

### 1.1 产品定义
ChatCFD 是一个基于 AI 的 CFD（计算流体力学）仿真数据智能分析平台。用户上传或指定仿真数据文件，通过自然语言对话即可完成数据读取、后处理分析、数据提取、数据对比等操作，快速获取所需信息。

### 1.2 核心价值
- **零门槛**：用户不需要学习后处理软件，用自然语言描述需求即可
- **快速**：一句话完成传统后处理软件需要多步操作才能完成的任务
- **云端可用**：通过网页访问，无需安装任何软件，支持云端示例数据试用

### 1.3 目标用户
- CFD 仿真工程师（需要快速查看/提取仿真结果）
- 项目经理/非仿真专业人员（需要查看仿真结论但不会用后处理软件）
- 潜在客户（通过云端 Demo 体验产品能力）

---

## 2. 系统架构

### 2.1 整体架构

```
                        ┌──────────────────┐
                        │   LLM API 服务    │
                        │ (Qwen/Claude/GPT) │
                        └────────▲─────────┘
                                 │
┌────────────────────────────────┼──────────────────────────────┐
│  Web 前端（Vue.js + VTK.js）    │                              │
│  对话界面 │ Artifact 侧边栏 │ 文件上传                         │
└──────┬─────────────────────────┼──────────────────────────────┘
       │ WS(对话)                │ HTTP(数据/上传)
       │                        │
┌──────▼────────────────────────┼──────────────────────────────┐
│  Agent 服务层                  │                              │
│  Harness │ Skill │ Prompt      │                              │
│  主 Agent │ MCP Client(SSE)    │                              │
│  子 Agent 池 │ Insight Log     │                              │
└──────────────┬─────────────────┼─────────────────────────────┘
               │ MCP(SSE)        │
               │ (summary给LLM)  │ HTTP API(大数据给前端)
               │                 │
┌──────────────▼─────────────────▼─────────────────────────────┐
│  后处理服务（同一个 HTTP 服务，两类端点）                       │
│                                                               │
│  ┌─────────────────────┐  ┌────────────────────────────────┐ │
│  │ MCP 端点 (SSE)       │  │ HTTP API 端点                  │ │
│  │ 6 个 tool 给 LLM     │  │ GET /mesh/{zone}  → 网格数据  │ │
│  │ 返回 summary(小数据) │  │ GET /scalar/{zone} → 标量     │ │
│  └──────────┬──────────┘  │ GET /file/{path}  → 文件下载   │ │
│             │              │ POST /upload      → 文件上传   │ │
│             │              └──────────┬─────────────────────┘ │
│             └──────────┬─────────────┘                        │
│                        ▼                                      │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  PostEngine（计算引擎，核心逻辑全在这里）                  │ │
│  │  Session Manager │ PostData(薄封装+物理量映射)             │ │
│  │  算法注册表(algorithms/ 插件) │ VTK 层(IO+Filters)        │ │
│  │  文件存储 │ 分析存档                                      │ │
│  └──────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────┘
```

要点：
- **一个 HTTP 服务，两类端点**：MCP SSE（给 Agent/LLM，返回 summary 小数据） + HTTP API（给前端，返回网格/表格等大数据）
- **前端双通道**：对话走 Agent → MCP，渲染数据直连 HTTP API，不经过 LLM
- **PostEngine 是核心**：MCP 端点和 HTTP API 端点都调用同一个 PostEngine，共享 Session Manager

<details>
<summary>旧版架构图（已弃用）— MCP Server 过重，所有逻辑堆在一起，前端无法直接取大数据</summary>

```
                        ┌──────────────────┐
                        │   LLM API 服务    │
                        │ (Qwen/Claude/GPT) │
                        └────────▲─────────┘
                                 │ LLM API (HTTP)
                                 │
┌────────────────────────────────┼──────────────────────────────┐
│                        Web 前端 │                              │
│                  （Vue.js / React）                            │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────────┐          │
│  │ 对话界面  │ │ 文件上传  │ │ 结果展示（表格/图表） │          │
│  └──────────┘ └────┬─────┘ └──────────────────────┘          │
└───────────┬────────┼─────────────────────────────────────────┘
            │ WS     │ HTTP(multipart)
            │对话     │文件上传
┌───────────▼────────▼─────────────────────────────────────────┐
│                    Agent 服务层                                │
│  Harness │ Skill │ Prompt                                     │
│  主 Agent │ MCP Client(SSE) │ 子 Agent 池 │ Insight Log       │
└──────────────────────┬───────────────────────────────────────┘
                       │ MCP (SSE)
┌──────────────────────▼───────────────────────────────────────┐
│            MCP Server（所有逻辑堆在这里）                      │
│  Session Manager                                              │
│  MCP Tools (6个)                                              │
│  PostData + 物理量映射表                                       │
│  算法注册表（轻型 + 重型）                                     │
│  VTK 层（IO + Filters）                                       │
│  文件存储 + 分析存档                                           │
└──────────────────────────────────────────────────────────────┘
```

弃用原因：
1. MCP Server 本职是暴露工具给 LLM，不应同时承担计算引擎、会话管理、文件存储
2. 前端渲染需要网格数据（几十MB），无法走 Agent → LLM → 前端 链路
3. 前端没有直连计算引擎的通道

</details>

### 2.2 数据流

#### 2.2.1 对话流

```
用户输入 → Web 前端(WS) → Agent 服务层
  → Harness 拦截检查
  → Skill 匹配？→ 是 → 按固化流程调用 MCP Tools
                → 否 → LLM 判断意图 → 选择 Tool → MCP Client 调用
  → MCP Server 执行 → 返回结果
  → Agent 组装回复 → Insight Log 记录 → Web 前端展示
```

#### 2.2.2 文件上传流

```
用户选择文件 → Web 前端(HTTP multipart)
  → Agent 服务层(文件暂存)
  → Harness 检查（大小/类型/白名单）
  → 存入 MCP Server 可访问的路径
  → 返回文件路径给 Agent
  → Agent 调用 loadFile(file_path=暂存路径)
```

#### 2.2.3 计算流（以力矩为例）

```
用户："算 wall 区域的升力系数"
  → Agent 调用 calculate(method="force_moment", zoneName="wall")
  → MCP Server:
      SessionState 取缓存的 PostData
      → PostData.get_vtk_data() 取 VTK 对象
      → ForceMomentIntegtal (C++) 执行计算
      → 返回 {"force":{...}, "moment":{...}, "coefficients":{...}}
  → Agent 精简回复："wall 区域升力系数 CL = 0.35"
  → Insight Log 记录 resolution: "tool_resolved"
```

### 2.3 会话与连接模型

| 概念 | 说明 |
|------|------|
| **Web 会话** | 用户打开网页到关闭，对应一个 session_id |
| **Agent 会话** | 一次对话上下文（含历史消息），对应同一个 session_id |
| **MCP 连接** | Agent → MCP Server 的 SSE 长连接，每个用户会话一条 |
| **SessionState** | MCP Server 内部，session_id → {PostData, output_dir}，用户间隔离 |

生命周期：
```
用户打开网页 → 创建 session_id
  → Agent 建立 MCP SSE 连接（带 session_id）
  → MCP Server 创建 SessionState
  → ... 对话 ...
  → 用户关闭网页 / 超时
  → Agent 关闭 SSE 连接
  → MCP Server 销毁 SessionState（释放 VTK 对象内存）
```

### 2.4 分层职责

| 层 | 职责 | 技术 | 归属 |
|----|------|------|------|
| Web 前端 | 用户交互、文件上传、结果展示 | Vue.js / React | 前端 |
| LLM API | 自然语言理解、工具选择 | Qwen / Claude / GPT API | 外部服务 |
| Harness | 安全拦截、资源限制 | Agent 框架代码 | Agent 服务层 |
| Skill / Prompt | 工作流引导、行为规范 | MCP Prompt + System Prompt | Agent 服务层 |
| 主 Agent | 对话管理、意图理解、简单任务执行 | 自研 Agent | Agent 服务层 |
| MCP Client | SSE 连接管理、tool_call 协议转换 | mcp SDK (Python) | Agent 服务层（主 Agent 组件） |
| 子 Agent | 多文件对比/AI Coding/报告生成 | 主 Agent 按需创建 | Agent 服务层 |
| Insight Log | 需求记录、统计分析 | JSONL 文件 | Agent 服务层 |
| Session Manager | 多用户会话隔离 | dict[session_id, SessionState] | MCP Server |
| MCP Tools | LLM 可调用的工具接口 | FastMCP (Python) | MCP Server |
| PostData | 薄封装访问层 | numpy + vtk_to_numpy | MCP Server |
| 算法注册表 | 算法管理、分发 | Python dict + register | MCP Server |
| VTK 算法层 | 重型几何/物理计算 | VTK + 自研 C++ 模块 | MCP Server |
| VTK IO 层 | 多格式文件读写 | vtkRomtekIODriver (C++) | MCP Server |
| 文件存储 | 数据文件 + 分析存档 | 文件系统 | MCP Server |

### 2.5 跨层约束对照

| 约束 | 实施层 | 实施方式 |
|------|--------|---------|
| 路径白名单 | Agent Harness | 调用 MCP 前校验 |
| 文件大小限制 | Agent Harness + Web 前端 | 前端预检 + 后端拦截 |
| 返回值截断 | Agent Harness | MCP 返回后截断再给 LLM |
| AI Coding 确认 | Agent Harness | 拦截 run_bash/runPythonString，要求确认标记 |
| 工作流引导 | Agent Skill | MCP Prompt 注入 |
| 行为规范 | Agent Prompt | System Prompt |
| 会话隔离 | MCP Session Manager | session_id → SessionState |
| 内存释放 | MCP Session Manager | 超时定时器清理 |
| 需求记录 | Agent Insight Log | 每次对话完成后追加 |
| 分析存档 | MCP Server | 用户主动触发写入 |

---

## 3. MCP 工具设计

### 3.1 设计原则

1. **最少工具数**：暴露给 LLM 的工具不超过 6 个，减少选择困难和 token 消耗
2. **一步到位**：能在工具内完成的决策不交给 AI（路径拼接、参数默认值、格式转换）
3. **会话状态**：加载文件后缓存，后续操作自动复用，不需要反复指定文件
4. **统一入口**：同类功能合成一个工具（所有计算 → `calculate`），用参数区分
5. **注册制扩展**：新增算法只注册一行，不增加工具数
6. **统一返回格式**：所有算法返回 `{type, summary, data, output_files}`，LLM 只看 summary
7. **工具描述互斥**：每个工具的 description 一句话说清什么时候用，不能有两个工具同时适用
8. **类型一致**：声明 `-> dict` 就必须所有分支返回 dict，包括错误分支

### 3.2 工具清单（6 个）

| # | 工具名 | 用户意图 | description（一句话，互斥） |
|---|--------|---------|---------------------------|
| 1 | `loadFile` | "我要看这个文件" | Load a CFD data file and return its summary. |
| 2 | `calculate` | "我要算一个东西" | Run a calculation on the loaded file and return numerical results. |
| 3 | `compare` | "帮我对比一下" | Compare data from two or more sources (zones, files, CSV). |
| 4 | `exportData` | "把数据拿出来" | Export data to a file (CSV, VTM, image). |
| 5 | `listFiles` | "有哪些文件" | List available files in a directory. |
| 6 | `getMethodTemplate` | "怎么用/需要什么参数" | Show available methods or parameters for a specific method. |

### 3.3 工具边界

| 判断条件 | 用哪个工具 |
|---------|-----------|
| 操作一份已加载数据，返回数值 | `calculate` |
| 涉及两份及以上数据源 | `compare` |
| 输出是文件（CSV/VTM/PNG） | `exportData` |
| 查看/加载文件 | `loadFile` |
| 浏览目录 | `listFiles` |
| 查参数/查能力 | `getMethodTemplate` |

### 3.4 统一返回格式

所有 `calculate` / `compare` / `exportData` 的算法统一返回此格式：

```json
{
  "type": "numerical",
  "summary": "wall区域升力系数CL=0.35，阻力系数CD=0.012",
  "data": {"force": {"x": 123.4}, "coefficients": {"CL": 0.35}},
  "output_files": []
}
```

| 字段 | 说明 | 谁消费 |
|------|------|--------|
| `type` | `"numerical"` / `"file"` / `"mixed"` | 前端判断展示方式 |
| `summary` | 一句话结论 | **LLM 直接念给用户**，控制 token |
| `data` | 详细数据 | 前端 Artifact 展示 |
| `output_files` | 生成的文件路径列表 | 前端 Artifact 列表 |

`summary` 由算法自己生成（算法最知道怎么总结自己的结果），LLM 不需要解析 `data`。

### 3.5 `calculate` 支持的 method（算法注册表）

#### 现有算法（已实现，依赖 VTK）

| method | 功能 | 依赖 VTK 的原因 |
|--------|------|----------------|
| `force_moment` | 力/力矩积分 | 需要网格面元法向量、面积、单元拓扑 |
| `velocity_gradient` | 速度梯度/涡量/Cp/马赫数 | 需要单元拓扑做梯度计算 |

#### 规划算法

| method | 功能 | 是否依赖 VTK |
|--------|------|:------------:|
| `statistics` | 标量统计（min/max/mean/std） | 否（numpy） |
| `probe` | 指定坐标点取值 | 是（需要空间查找） |
| `slice` | 切片提取 | 是（几何操作） |
| `streamline` | 流线计算 | 是（向量场追踪） |
| `contour` | 等值面提取 | 是（几何操作） |
| `surface_extract` | 提取表面数据 | 是（边界识别） |
| `render` | 离屏渲染生成云图/截图 | 是（VTK 渲染） |

### 3.6 `compare` 工具

独立于 `calculate`，凡涉及两份及以上数据源的操作归此工具。

| 场景 | 调用示例 |
|------|---------|
| 两个区域对比 | `compare(source_a="wall:Pressure", source_b="far:Pressure")` |
| CFD 结果 vs 实验 CSV | `compare(source_a="wall:Pressure", file_b="experiment.csv", column_b="Cp")` |
| 两个文件对比 | `compare(file_a="case1.cgns", file_b="case2.cgns", scalar="Pressure")` |

### 3.7 `exportData` 工具

解决用户"提取表面压力数据"、"导出 CSV" 等需求，避免 LLM 用 `run_bash` 手写代码。

| 功能 | 参数示例 |
|------|---------|
| 导出区域标量到 CSV | `exportData(zone="wall", scalars=["Pressure","Temperature"], format="csv")` |
| 导出到 JSON | `exportData(zone="wall", format="json")` |
| 导出到 VTM | `exportData(format="vtm")` |

---

## 4. 数据层设计（PostData）

### 4.1 目标

为 VTK 数据提供一个**薄封装访问层**，让轻型算法通过 numpy 接口操作数据，不需要直接使用 VTK API。PostData 不复制数据，所有数据的唯一来源是 VTK 对象。

### 4.2 方案：薄封装（零拷贝访问）

```
vtkMultiBlockDataSet（唯一数据源，缓存在 SessionState）
        ↓
PostData（薄封装，不存数据，实时从 VTK 取）
    ├── get_scalar("wall", "Pressure") → vtk_to_numpy() 零拷贝
    ├── get_zones()                    → 返回区域名列表
    ├── get_bounds("wall")             → 返回包围盒
    ├── get_summary()                  → 返回精简摘要给 LLM
    ↓                    ↓
轻型算法              重型算法
(拿到numpy操作)      (直接用VTK对象)
```

### 4.3 接口定义

```python
class PostData:
    """VTK 数据的薄封装访问层。不复制数据，通过 vtk_to_numpy 零拷贝引用 VTK 内存。"""

    def __init__(self, multiblock: vtkMultiBlockDataSet, file_path: str):
        self._multiblock = multiblock   # 持有引用，不复制
        self.file_path = file_path

    def get_zones(self) -> list[str]:
        """返回所有区域名称"""

    def get_scalar(self, zone: str, name: str) -> np.ndarray:
        """零拷贝返回指定区域的标量数组（numpy 视图，只读）"""
        # 内部使用 vtk_to_numpy()，直接引用 VTK 内存
        # arr.flags.writeable = False 防止意外修改 VTK 底层数据
        # 算法如需修改数据，必须显式 arr.copy()

    def get_points(self, zone: str) -> np.ndarray:
        """零拷贝返回节点坐标 (N, 3)"""

    def get_scalar_names(self, zone: str) -> list[str]:
        """返回指定区域的所有标量名"""

    def get_bounds(self, zone: str) -> dict:
        """返回包围盒"""

    def get_summary(self) -> dict:
        """返回精简摘要（区域列表、标量范围、网格规模），供 LLM 消费"""

    def get_vtk_data(self) -> vtkMultiBlockDataSet:
        """返回底层 VTK 对象，重型算法直接使用"""
```

### 4.4 为什么不复制数据

| 方案 | 内存 | 数据一致性 | 性能 |
|------|:----:|:----------:|:----:|
| 复制一份 numpy 副本 | 翻倍（CFD 数据几百 MB~GB） | VTK 计算后两边不同步 | 加载时慢（复制耗时） |
| **薄封装零拷贝（选定）** | 不增加 | 永远一致（同一块内存） | 取值时即时，无额外开销 |

### 4.5 风险与应对

| # | 风险 | 严重程度 | 应对 |
|---|------|:--------:|------|
| 1 | **VTK 对象被提前释放**，numpy 视图变成野指针，程序崩溃 | 高 | SessionState 持有 VTK 对象引用，生命周期与会话绑定，不提前释放 |
| 2 | **VTK Filter 修改原始数据**（如速度梯度计算加新标量），LLM 不知道有新数据 | 中 | 重型算法执行完后自动刷新 `get_summary()`，通知 LLM 数据变化 |
| 3 | **vtk_to_numpy 对特殊数组类型不支持零拷贝** | 低 | CFD 数据基本都是 float64/float32，均支持零拷贝 |
| 4 | **多用户并发共享 VTK 对象**，一个用户的计算影响另一个 | 高 | 每个会话独立 SessionState，不共享 VTK 对象 |
| 5 | **云端多用户同时加载大文件，内存压力** | 中 | 文件大小上限 + 会话超时自动释放 + 限制并发数 |

### 4.6 VTK 耦合边界

只有以下场景需要直接操作 VTK 对象（通过 `post_data.get_vtk_data()` 获取）：

| 场景 | 原因 |
|------|------|
| **文件读取** | `vtkRomtekIODriver` 是 C++ 实现的多格式 reader |
| **力/力矩积分** | `ForceMomentIntegtal` 需要面元法向量、面积、单元拓扑 |
| **速度梯度计算** | `CalculateVelocityGradient` 需要单元拓扑做有限差分 |
| **切片/流线/等值面** | `SliceFilter`/`VectorFlowLineFilter`/`ContourPlaneFilter` 是几何操作 |
| **空间探针** | 点定位需要 VTK 的空间搜索结构 |
| **体渲染数据** | `VolumeRenderFilter` 需要体素化插值 |
| **文件写出（VTM/VTS等）** | VTK writer |

通过 PostData 的 numpy 接口即可完成的场景（不需要 VTK）：
- 标量统计（min/max/mean/std）→ `get_scalar()` + numpy
- 数据导出 CSV/JSON → `get_scalar()` + `get_points()` + 标准库
- 数据对比 → 两个 PostData 的 `get_scalar()` 做差
- 绘图 → `get_scalar()` + matplotlib

### 4.7 物理量映射表

#### 为什么需要映射表

不同 CFD 求解器对同一个物理量的命名完全不同：

| 物理量 | Fluent | OpenFOAM | CGNS | 用户可能说 |
|--------|--------|----------|------|-----------|
| 压力 | `Static_Pressure` | `p` | `Pressure` | "压力"、"P" |
| 密度 | `Density` | `rho` | `Density` | "密度" |
| x 速度 | `X_Velocity` | `Ux` | `VelocityX` | "x方向速度" |
| y 速度 | `Y_Velocity` | `Uy` | `VelocityY` | "y方向速度" |
| z 速度 | `Z_Velocity` | `Uz` | `VelocityZ` | "z方向速度" |
| 温度 | `Static_Temperature` | `T` | `Temperature` | "温度" |
| 马赫数 | `Mach_Number` | `Ma` | `Mach` | "马赫数" |
| 压力系数 | `Pressure_Coefficient` | `Cp` | `CoefPressure` | "Cp" |

**没有映射表的后果**：
1. 用户说"看压力"，AI 不知道该文件里压力叫什么 → 只能列出所有标量让用户选，体验差
2. 算法 DEFAULTS 里 `pressure="Pressure"`，但文件里叫 `Static_Pressure` → 直接报错"标量不存在"
3. 同一个用户换了求解器的数据，之前能跑的参数全部失效
4. AI 每次都要先 getMethodTemplate → loadFile 看标量名 → 手动匹配 → 填参数，多了 2-3 步调用

#### 映射表在哪一层

**在 PostData 薄封装层**。PostData 是唯一连接"VTK 原始数据"和"上层消费者"的桥梁，映射自然在这里做。

```
VTK IO 读出文件 → 原始标量名 "Static_Pressure"
        ↓
PostData 层（映射发生在这里）
  get_scalar("wall", "pressure")  ← 用户/算法用标准名
  内部查映射表 → "pressure" → ["Pressure", "Static_Pressure", "p"]
  遍历候选名 → 找到 "Static_Pressure" → vtk_to_numpy 返回
        ↓
算法层 → 拿到 numpy 数组，完全不关心底层标量叫什么
```

上层（MCP Tools、算法、LLM）统一使用标准物理量名，PostData 内部自动翻译成文件里的实际名称。

#### 映射表格式

独立配置文件 `config/physical_mapping.json`：

```json
{
  "pressure": {
    "standard_name": "pressure",
    "display_name": "压力",
    "unit": "Pa",
    "aliases": ["Pressure", "Static_Pressure", "p", "P", "PRES"]
  },
  "density": {
    "standard_name": "density",
    "display_name": "密度",
    "unit": "kg/m³",
    "aliases": ["Density", "rho", "RHO"]
  },
  "velocity_x": {
    "standard_name": "velocity_x",
    "display_name": "X方向速度",
    "unit": "m/s",
    "aliases": ["VelocityX", "X_Velocity", "Ux", "U:0", "x-velocity"]
  },
  "temperature": {
    "standard_name": "temperature",
    "display_name": "温度",
    "unit": "K",
    "aliases": ["Temperature", "Static_Temperature", "T", "TEMP"]
  },
  "mach": {
    "standard_name": "mach",
    "display_name": "马赫数",
    "unit": "",
    "aliases": ["Mach", "Mach_Number", "Ma", "MACH"]
  },
  "cp": {
    "standard_name": "cp",
    "display_name": "压力系数",
    "unit": "",
    "aliases": ["CoefPressure", "Pressure_Coefficient", "Cp", "CP"]
  }
}
```

#### PostData 的映射逻辑

```python
class PostData:
    def __init__(self, multiblock, file_path):
        self._multiblock = multiblock
        self.file_path = file_path
        self._mapping = load_physical_mapping()   # 加载映射表
        self._resolved = {}                        # 缓存已解析的映射 {"pressure": "Static_Pressure"}

    def get_scalar(self, zone, name):
        actual_name = self._resolve_name(zone, name)
        arr = vtk_to_numpy(...)
        arr.flags.writeable = False
        return arr

    def _resolve_name(self, zone, name):
        """标准名 → 文件中的实际标量名"""
        # 1. 如果 name 在文件中直接存在，直接用
        if self._has_raw_scalar(zone, name):
            return name
        # 2. 查映射表，遍历 aliases
        if name in self._mapping:
            for alias in self._mapping[name]["aliases"]:
                if self._has_raw_scalar(zone, alias):
                    self._resolved[name] = alias
                    return alias
        # 3. 都找不到，报错并列出可用标量
        available = self.get_scalar_names(zone)
        raise ValueError(f"'{name}' not found. Available: {available}")
```

#### loadFile 时的自动识别

`loadFile` 返回的 summary 中，标量名自动标注标准物理量：

```json
{
  "zones": ["wall"],
  "scalars": [
    {"raw_name": "Static_Pressure", "mapped_to": "pressure", "display": "压力(Pa)"},
    {"raw_name": "X_Velocity", "mapped_to": "velocity_x", "display": "X方向速度(m/s)"},
    {"raw_name": "MyCustomField", "mapped_to": null, "display": "MyCustomField（未识别）"}
  ]
}
```

LLM 看到 `mapped_to` 就知道该用什么标准名调算法，未识别的标量用原始名。

#### 可扩展性

- 用户遇到新的求解器命名 → 往 `physical_mapping.json` 的 aliases 里加一个就行
- 新增物理量 → 加一个条目
- 不改任何代码

---

## 5. 会话状态管理

### 5.1 缓存策略

```python
class SessionState:
    post_data: PostData         # 薄封装层（内部持有 VTK 对象引用）
    output_dir: str             # 输出目录 = 文件所在目录

    # 通过 post_data 访问一切：
    # post_data.file_path          → 文件路径
    # post_data.get_scalar(...)    → numpy 数组（零拷贝）
    # post_data.get_vtk_data()     → 底层 VTK 对象（重型算法用）
    # post_data.get_summary()      → 精简摘要（给 LLM）
```

### 5.2 缓存规则

| 场景 | 行为 |
|------|------|
| `loadFile("a.cgns")` | 加载文件，缓存 PostData + VTK 数据 |
| `calculate(method="force_moment")` | 用缓存，不重新加载 |
| `calculate(method="statistics", file_path="b.cgns")` | 路径不同，重新加载 |
| `calculate(method="statistics")` 无缓存 | 返回错误：请先加载文件 |
| `extractData(zone="wall", ...)` | 用缓存的 PostData，不需要 VTK |

### 5.3 输出目录

- 不要求用户设置工作目录
- 自动使用已加载文件的所在目录作为输出目录
- 示例：加载 `D:/XField/data/cgns/ysy.cgns` → 输出到 `D:/XField/data/cgns/`

---

## 6. AI 约束分层设计

约束可靠性从高到低：Harness > Skill > Prompt。**能放 Harness 的不放 Skill，能放 Skill 的不放 Prompt。**

```
┌──────────────────────────────────────────────────┐
│  Prompt（软约束）                                  │
│  AI 大部分时候遵守，复杂场景可能违反                 │
│  ┌──────────────────────────────────────────────┐ │
│  │  Skill（中约束）                               │ │
│  │  固化工作流，AI 看到就按步骤走                   │ │
│  │  ┌──────────────────────────────────────────┐ │ │
│  │  │  Harness（硬约束）                        │ │ │
│  │  │  代码强制执行，AI 无法绕过                 │ │ │
│  │  └──────────────────────────────────────────┘ │ │
│  └──────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────┘
```

### 6.1 Harness（硬约束 — 代码层强制执行）

安全相关、资源相关的约束，不能靠 AI 自觉，必须在代码层拦截。

| 约束项 | 实现方式 | 说明 |
|--------|---------|------|
| 文件路径白名单 | Agent 框架层校验 | 只能访问指定目录，防止读系统文件 |
| 文件大小上限 | `loadFile` 内检查 | 超过限制直接拒绝，不交给 AI 判断 |
| Tool 返回值截断 | MCP Server 中间件 | 超过 N 字符自动截断，防止 token 爆炸 |
| run_bash 命令黑名单 | `bash_tool.py` 内拦截 | `rm`/`sudo`/`shutdown` 等危险命令直接拒绝 |
| 单次计算超时 | Tool 执行层 | 超过 N 秒强制终止，防止死循环 |
| 会话超时释放内存 | SessionState 定时器 | 超时自动清理 VTK 对象，防止内存泄漏 |
| 并发数限制 | MCP Server 层 | 云端部署时限制同时加载的文件数 |
| 上传文件类型限制 | 上传接口校验 | 只接受 .cgns/.plt/.dat/.vtm/.case 等后处理格式 |

### 6.2 Skill（中约束 — 固化工作流）

把常见业务操作固化成标准步骤，AI 看到 Skill 就按流程走，不自由发挥。通过 MCP Prompt 注册。

| Skill | 触发条件 | 固化流程 |
|-------|---------|---------|
| 文件分析 | 用户提到文件名 | `loadFile → 读 summary → 简要告诉用户有哪些区域和标量` |
| 力矩计算 | 用户说"力/力矩/升力/阻力/CL/CD" | `确认文件已加载 → calculate(method="force_moment") → 返回力和力矩结果` |
| 速度梯度 | 用户说"涡量/马赫数/Cp/声速" | `确认文件已加载 → calculate(method="velocity_gradient") → 告诉用户输出文件位置` |
| 数据提取 | 用户说"提取/导出/CSV/表面压力" | `确认区域和标量 → extractData → 告诉用户文件路径` |
| 数据对比 | 用户说"对比/比较/差异" | `确认两个文件或区域 → calculate(method="compare") → 返回差异摘要` |
| 参数查询 | 用户说"需要什么参数/怎么设置" | `getMethodTemplate → 展示参数表` |

MCP Prompt 实现示例：

```python
@mcp.prompt()
def workflow_guide():
    """ChatCFD workflow guide for LLM"""
    return """你是 ChatCFD 智能助手。遵循以下工作流：

常见对话与对应操作：
  用户提到文件名          → loadFile(file_path=...)
  用户说"算力和力矩"      → calculate(method="force_moment")
  用户说"算涡量/马赫数"   → calculate(method="velocity_gradient")
  用户说"提取数据/导出"   → extractData(zone=..., scalars=...)
  用户说"有哪些算法"      → getMethodTemplate()

重要规则：
  - loadFile 只需调一次，后续操作自动复用已加载的文件
  - 不要用 run_bash 写 Python 脚本来做 calculate/extractData 能做的事
  - 参数不确定时先问用户，不要猜默认值
"""
```

### 6.3 Prompt（软约束 — 行为规范）

约束 AI 的语言风格、输出格式、兜底行为。AI 大部分时候遵守，但无法强制。

| 类别 | 约束内容 |
|------|---------|
| **身份** | "你是 ChatCFD 智能助手，专注 CFD 仿真数据分析" |
| **简洁** | "回答简短直接，不要重复 tool 返回的完整 JSON 数据" |
| **不编造** | "只使用系统提供的工具，不要编造不存在的工具或功能" |
| **不绕路** | "不要用 run_bash 手写 Python 来替代已有的工具" |
| **先确认** | "参数不确定时先问用户（如参考面积、来流密度），不要用默认值静默计算" |
| **单位** | "力的单位是 N，压力单位是 Pa，长度单位是 m，除非用户指定其他单位制" |
| **错误处理** | "工具返回 error 时，向用户解释原因并建议下一步操作" |

### 6.4 三层协作示例

用户说："算一下 ysy.cgns 的升力系数"

```
Harness 层：
  ✓ 文件路径在白名单内
  ✓ 文件大小未超限

Skill 层（力矩计算流程）：
  1. 检查文件是否已加载 → 未加载 → loadFile("ysy.cgns")
  2. calculate(method="force_moment")
  3. 返回结果中的 lift_coefficient

Prompt 层：
  ✓ 发现用户没给参考面积和来流条件 → 先问用户
  ✓ 结果简短展示："升力系数 CL = 0.35"
  ✓ 不把完整的 force/moment JSON 全部输出
```

---

## 7. 现有 C++ 模块清单

### 7.1 RomtekIODriver（文件读取）

| Reader | 支持格式 | 说明 |
|--------|---------|------|
| CGNSReader | .cgns, .cga | CFD 通用格式 |
| TecplotReader | .plt, .dat | Tecplot 格式 |
| EnsightReader | .case | EnSight 格式 |
| VTKVTMReader | .vtm | VTK 多块格式 |
| VTKVTSReader | .vts | VTK 结构化网格 |
| VTKVTUReader | .vtu | VTK 非结构化网格 |
| VTKVTPReader | .vtp | VTK 多边形数据 |

### 7.2 RomtekAnalysis（分析算法）

| 算法 | 功能 | 对应 method |
|------|------|------------|
| ForceMomentIntegtal | 力/力矩积分，气动系数计算 | `force_moment` |
| CalculateVelocityGradient | 速度梯度、涡量、Cp、声速、马赫数 | `velocity_gradient` |

### 7.3 RomtekVtkAlgorithm（VTK 滤波器）

| Filter | 功能 | 对应 method |
|--------|------|------------|
| SliceFilter | 切片 | `slice`（规划） |
| ContourPlaneFilter | 等值面 | `contour`（规划） |
| VectorFlowLineFilter | 流线 | `streamline`（规划） |
| VectorFieldFilter | 向量场生成 | `vector_field`（规划） |
| IdwInterpolation | 反距离加权插值 | 内部使用 |
| LinearInterpolation | 线性插值 | 内部使用 |
| SurfaceFilter | 表面提取 | `surface_extract`（规划） |
| VolumeRenderFilter | 体渲染数据准备 | `volume_render`（规划） |

---

## 8. 部署方案

### 8.1 云端 Demo 模式（优先实现）

```
云服务器
├── MCP Server（后处理服务）
├── Agent 服务（LLM 调度）
├── Web 前端（静态文件）
├── 示例数据/
│   ├── ysy.cgns        （航空外流）
│   ├── hr.plt          （某典型算例）
│   └── ...
└── 用户上传临时目录/（可选，后期加）
```

- 用户打开网页即可使用，无需安装
- 示例数据预置在服务器上
- 文件白名单机制，限制可访问路径

### 8.2 本地部署模式

```
用户本机
├── MCP Server（读本地数据）
├── Agent 服务（可本地或远程）
└── 用户数据/（任意路径）
```

- 适合处理大文件（几百 MB ~ GB）
- 数据不离开用户本机

### 8.3 混合模式（未来）

```
用户本机                          云端
├── MCP Server ◄── SSE ──── MCP Gateway
└── 用户数据                   ├── Agent 服务
                               └── Web 前端
```

- LLM 在云端，数据处理在用户本地
- 数据不上传，只传分析结果

---

## 9. 算法插件化

### 9.1 目录结构

```
MCP_PostDrive/
├── algorithms/                    ← 算法插件目录
│   ├── force_moment.py            ← 一个文件 = 一个算法
│   ├── velocity_gradient.py
│   ├── statistics.py
│   └── my_new_algorithm.py        ← 放进来重启即生效
├── MCP_Tools/
│   └── quick_tools.py             ← calculate 内部自动扫描 algorithms/
└── mcp_run.py
```

### 9.2 算法文件规范

每个算法文件实现固定接口：

```python
# algorithms/force_moment.py

NAME = "force_moment"
DESCRIPTION = "Calculate force and moment integral (CL, CD, etc.)"

# 参数默认值模板（dict，不用 class）
# None = 无默认值，用户不给时 AI 应该反问
DEFAULTS = {
    "pressure": "Pressure",
    "density": None,
    "velocity": None,
    "refArea": None,
    "refLength": None,
    "flip_normals": True,
    "alpha_angle": 0.0,
    "beta_angle": 0.0,
}

def execute(post_data, params: dict, zone_name: str) -> dict:
    """
    固定签名。MCP Server 自动调用。
    
    Args:
        post_data: PostData 薄封装层
        params: 用户参数（已用 DEFAULTS 填充缺失字段）
        zone_name: 区域名（空字符串 = 所有区域合并）
    
    Returns:
        统一返回格式 {type, summary, data, output_files}
    """
    vtk_data = post_data.get_vtk_data()
    # ... VTK 计算 ...
    return {
        "type": "numerical",
        "summary": f"力: Fx={fx:.2f}N; 升力系数CL={cl:.4f}",
        "data": {"force": {...}, "coefficients": {...}},
        "output_files": []
    }
```

### 9.3 自动加载机制

MCP Server 启动时扫描 `algorithms/` 目录：

```python
import importlib, os

METHODS = {}

for filename in os.listdir("algorithms"):
    if filename.endswith(".py") and not filename.startswith("_"):
        module = importlib.import_module(f"algorithms.{filename[:-3]}")
        METHODS[module.NAME] = {
            "description": module.DESCRIPTION,
            "defaults": module.DEFAULTS,
            "execute": module.execute,
        }
```

`calculate` 内部永远不改：

```python
def calculate(method, params, zone_name):
    entry = METHODS[method]
    merged = {**entry["defaults"], **params}  # DEFAULTS 填充缺失字段
    return entry["execute"](post_data, merged, zone_name)
```

### 9.4 新增算法流程

1. 在 `algorithms/` 下新建 `.py` 文件
2. 实现 `NAME`、`DESCRIPTION`、`DEFAULTS`、`execute()`
3. 重启 MCP Server
4. 无需修改任何其他代码

不做热插拔（Phase 1）。重启只需几秒，算法增加频率低。

---

## 10. 代码质量规范

### 10.1 参数填充

使用 DEFAULTS dict 合并替代逐字段 if-else：
```python
# 禁止：20 个 if
if "pressure" in params: struct.pressure = params["pressure"]
if "density" in params: struct.density = params["density"]

# 要求：一行合并
merged = {**DEFAULTS, **user_params}
```

### 10.2 返回类型一致

所有 MCP tool 返回 `dict`，包括错误分支：
```python
# 禁止
return "error: file not found"

# 要求
return {"error": "file not found"}
```

### 10.3 路径处理

- 接收路径后统一 `normpath` + `replace('\\', '/')`
- 支持正斜杠和反斜杠
- 相对路径自动拼接已加载文件的目录
- 路径不存在时返回清晰错误信息

### 10.4 Token 控制

- Tool description 一句话，不写"转成 Markdown 表格"等格式化指令
- 返回值统一格式，LLM 只看 summary 字段
- 大数据通过 `exportData` 导出文件，不通过 tool 返回值传递

---

## 11. 子 Agent 设计

### 11.0 为什么需要子 Agent

**根因：LLM 的上下文窗口是有限资源。**

主 Agent 的对话历史会持续增长（用户消息 + 工具返回值 + AI 回复），而某些操作会向上下文注入大量数据：

| 操作 | 上下文膨胀量 | 影响 |
|------|:----------:|------|
| 加载一个文件的 summary | ~500 tokens | 可控 |
| 同时加载两个文件做对比 | ~1000+ tokens | 开始吃紧 |
| AI Coding 脚本 + 执行输出 | ~2000~5000 tokens | 严重挤占后续对话空间 |
| 多步分析生成报告（5~10 步） | ~3000~8000 tokens | 可能触发上下文压缩，丢失早期信息 |

**如果全在主 Agent 里做**：
- 上下文快速膨胀 → LLM 性能下降（注意力稀释）
- Token 费用线性增长（每次 LLM 调用都带完整历史）
- 中间过程数据（脚本输出、多步分析中间结果）永久留在对话历史中，后续每轮对话都要为它们付费

**子 Agent 解决的核心问题**：
- **上下文隔离** — 子 Agent 用干净上下文执行，中间过程不回到主对话
- **Token 控制** — 子 Agent 的完整执行过程可能消耗 5000 tokens，但主 Agent 只收到一句 50 tokens 的摘要
- **执行隔离** — AI Coding 的脚本执行失败/输出异常不会污染主对话的稳定性

**引入子 Agent 的代价**：

| 代价 | 说明 | 应对 |
|------|------|------|
| **开发复杂度增加** | 需要实现子 Agent 创建/销毁/通信机制 | Phase 3 再实现，Phase 1-2 不引入 |
| **额外 LLM 调用** | 子 Agent 独立调 LLM，主 Agent 调度也要一次 LLM 判断 → 至少多一次 API 调用 | 仅 3 种场景触发，低频 |
| **延迟增加** | 主 Agent 判断 → 创建子 Agent → 子 Agent 执行 → 返回摘要，链路变长 | 可提示用户"正在执行复杂分析..." |
| **调试困难** | 子 Agent 的上下文执行完就销毁，出问题不好复现 | Insight Log 记录子 Agent 的任务描述和返回摘要 |
| **SessionState 竞争** | 子 Agent 和主 Agent 共享 SessionState，子 Agent 加载新文件会覆盖缓存 | 对比子 Agent 执行完恢复原缓存，或用独立的临时 SessionState |

**结论：子 Agent 不是必需品**。它是应对 token 爆炸的实用工具，代价是增加了系统复杂度和延迟。如果 LLM 上下文窗口足够大且成本足够低，可以完全不用子 Agent。因此放在 **Phase 3** 实现，Phase 1-2 全部由主 Agent 直接处理。

### 11.1 层级结构

```
┌─────────────────────────────────────────────────────────┐
│  主 Agent（常驻，1 个）                                   │
│  ┌───────────────────────────────────────────────────┐  │
│  │ 职责：                                             │  │
│  │ - 和用户对话，理解意图                              │  │
│  │ - 简单任务自己做（loadFile/calculate/exportData等） │  │
│  │ - 复杂任务判断后派子 Agent                          │  │
│  │ - 接收子 Agent 摘要，组装回复给用户                  │  │
│  └───────────────────────────────────────────────────┘  │
│       │ 创建（按需）          │ 创建（按需）               │
│       ▼                      ▼                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ 对比子 Agent  │  │ Coding子Agent│  │ 报告子 Agent  │  │
│  │              │  │              │  │              │  │
│  │ 干净上下文    │  │ 干净上下文    │  │ 干净上下文    │  │
│  │ 可调MCP Tools│  │ 可调MCP Tools│  │ 可调MCP Tools│  │
│  │ 只返回摘要   │  │ 需用户确认   │  │ 只返回摘要   │  │
│  │ 完成即销毁   │  │ 完成即销毁   │  │ 完成即销毁   │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────┘
         │                    │                  │
         └────────────────────┴──────────────────┘
                              │
                     MCP Client (SSE)
                              │
                     MCP Server (共享)
```

### 11.2 主 Agent 与子 Agent 的边界

| | 主 Agent | 子 Agent |
|---|---------|---------|
| **数量** | 1 个，常驻 | 0~N 个，按需创建 |
| **生命周期** | 跟随用户会话 | 任务完成即销毁 |
| **上下文** | 完整对话历史 | 只有主 Agent 给的任务描述，干净上下文 |
| **和用户的关系** | 直接对话 | **不直接和用户对话**，只通过主 Agent 中转 |
| **调用 MCP Tools** | 直接调用 | 通过同一个 MCP Client 调用，共享 SessionState |
| **返回给谁** | 返回给用户 | 只返回一句摘要给主 Agent |
| **LLM 调用** | 使用会话级 LLM 上下文 | 独立 LLM 调用，不继承主 Agent 的消息历史 |

### 11.3 什么时候用子 Agent，什么时候不用

#### 主 Agent 自己做（绝大多数场景）

| 场景 | 为什么不需要子 Agent |
|------|-------------------|
| 加载文件 `loadFile` | 一步操作，上下文开销小 |
| 单次计算 `calculate` | 一步操作，返回值已是精简摘要 |
| 导出数据 `exportData` | 一步操作 |
| 列出文件 `listFiles` | 一步操作 |
| 查参数 `getMethodTemplate` | 一步操作 |
| 单文件内区域对比 | `compare` 一步完成，数据量可控 |

#### 派子 Agent（仅 3 种场景）

| 场景 | 子 Agent 类型 | 为什么需要隔离 | 主 Agent 收到的摘要示例 |
|------|-------------|--------------|----------------------|
| 多文件对比 | 对比子 Agent | 两个文件的 summary 同时在上下文会撑爆 token | "ysy.cgns 与 abc.cgns 的 wall 区域压力最大差异 12.3%" |
| AI Coding | Coding 子 Agent | 脚本和中间输出可能很长，污染主对话 | "已生成 Cp 分布曲线，保存到 cp_plot.png" |
| 完整报告生成 | 报告子 Agent | 多步分析（加载→统计→力矩→梯度→...），中间数据量大 | "ysy.cgns 分析报告：3个区域，CL=0.35，最大马赫数20.28..." |

### 11.4 约束规则

1. **子 Agent 不是必需品** — 它是应对 token 爆炸的工具，不是架构必需层。如果未来 LLM 上下文窗口足够大，子 Agent 可以完全不用
2. **不得滥用** — 不能因为加了子 Agent 给软件增加不必要的负担。能一步做完的事不派子 Agent
3. **主 Agent 是唯一的用户接口** — 子 Agent 永远不直接和用户对话
4. **子 Agent 共享 MCP 连接** — 不为每个子 Agent 建立独立的 MCP SSE 连接，共用主 Agent 的连接
5. **子 Agent 共享 SessionState** — 主 Agent 加载的文件，子 Agent 可以直接用，不需要重新加载
6. **AI Coding 子 Agent 需用户确认** — 由主 Agent 先问用户，确认后才创建 Coding 子 Agent 执行

### 11.5 交互模式详解

#### 场景 1：多文件对比

```
用户："对比 ysy.cgns 和 abc.cgns 的压力"
主 Agent：
  判断 → 涉及两个文件 → 需要对比子 Agent
  创建子 Agent，任务描述：
    "加载 ysy.cgns 和 abc.cgns，对比 wall 区域的 Pressure，返回差异摘要"
  
  对比子 Agent（干净上下文）：
    → loadFile("ysy.cgns") → 取 wall:Pressure 统计
    → loadFile("abc.cgns") → 取 wall:Pressure 统计
    → compare(...)
    → 返回摘要："wall 区域压力最大差异 12.3%，均值差异 2.1%"
    → 销毁
  
主 Agent：收到摘要 → 回复用户
```

#### 场景 2：AI Coding

```
用户："画 wall 沿 x 方向的 Cp 分布"
主 Agent：
  判断 → 没有 plot method → 需要写代码
  先问用户："我需要编写 Python 脚本来生成 Cp 分布曲线，是否允许？"
用户："可以"
主 Agent：
  创建 Coding 子 Agent，任务描述：
    "从已加载文件的 wall 区域提取坐标和 Cp，用 matplotlib 生成沿 x 方向的分布曲线"
  
  Coding 子 Agent（干净上下文）：
    → get_scalar("wall", "CoefPressure")
    → 编写 matplotlib 脚本
    → 执行脚本（中间输出留在子 Agent 上下文，不回到主对话）
    → 返回摘要："Cp 分布曲线已生成，保存到 cp_distribution.png"
    → 销毁
  
主 Agent：收到摘要 + 文件路径 → 推送到 Artifact → 回复用户
```

#### 场景 3：完整报告

```
用户："给我一份 ysy.cgns 的完整分析报告"
主 Agent：
  判断 → 多步分析，中间数据量大 → 需要报告子 Agent
  创建报告子 Agent，任务描述：
    "对 ysy.cgns 进行完整分析：文件概要、各区域统计、力矩计算、关键发现"
  
  报告子 Agent（干净上下文）：
    → loadFile("ysy.cgns") → 文件概要
    → calculate(method="statistics") → 各区域标量统计
    → calculate(method="force_moment") → 力矩结果
    → 综合分析，生成报告
    → 返回摘要："ysy.cgns 包含 3 个区域，403035 单元。wall 区域 CL=0.35，
                马赫数异常高(20.28)建议检查边界条件。完整报告见附件。"
    → 销毁
  
主 Agent：收到摘要 + 报告文件 → 推送到 Artifact → 回复用户
```

---

## 12. AI Coding 能力

### 12.1 需求

当用户的需求超出现有工具能力时，AI 可以编写并执行自定义脚本。但必须**先征得用户同意**，防止 AI 自作主张。

### 12.2 实现

在 Harness 层拦截 `run_bash` / `runPythonString` 的调用：

```python
# Harness 层
def before_tool_call(tool_name, args):
    if tool_name in ("run_bash", "runPythonString"):
        # 要求 AI 必须先获得用户确认
        if not session.user_confirmed_coding:
            return {"error": "需要用户确认后才能执行自定义代码。请先询问用户。"}
```

### 12.3 对话流程

```
用户："帮我画一个壁面压力分布曲线"
AI：  "当前工具没有绘图功能。我可以编写 Python 脚本来：
       1. 提取 wall 区域的坐标和压力数据
       2. 用 matplotlib 生成压力分布曲线
       是否允许执行？"
用户："可以"
AI：  执行脚本 → 返回图片路径
```

### 12.4 安全约束（Harness 层）

| 约束 | 说明 |
|------|------|
| 执行前必须用户确认 | AI 不能静默执行代码 |
| 脚本长度限制 | 单次脚本不超过 2000 字符 |
| 执行超时 | 60 秒超时强制终止 |
| 危险命令拦截 | rm/sudo/shutdown 等直接拒绝 |
| 输出截断 | 结果超过 5000 字符截断 |

---

## 13. 前端 Artifact 设计

### 13.1 布局

类似 Claude Artifacts 的侧边栏模式：

```
┌──────────────────────────────────┬────────────────────────────┐
│         对话区域                  │       Artifact 区域         │
│                                  │                            │
│  用户: 分析 ysy.cgns             │   ┌────────────────────┐   │
│                                  │   │                    │   │
│  AI: 文件已加载                  │   │  当前查看的内容      │   │
│      3个区域: solid/far/wall     │   │  （3D / 表格 / 图表）│   │
│      📎 文件概要                 │   │                    │   │
│                                  │   └────────────────────┘   │
│  用户: 算力矩                    │                            │
│                                  │   ── Artifacts ──────────  │
│  AI: CL=0.35, CD=0.012          │   📄 文件概要         [👁]  │
│      📎 力矩结果                 │   📊 力矩结果         [👁]  │
│                                  │   🧊 wall压力云图     [👁]  │
│  用户: 看 wall 压力云图          │   📄 wall压力.csv     [👁]  │
│                                  │                            │
│  AI: 已渲染                      │   [👁] = 点击查看          │
│      📎 wall压力云图              │   当前展开的高亮显示        │
└──────────────────────────────────┴────────────────────────────┘
```

### 13.2 交互规则

- 对话中产生的每个结果自动变成一个 Artifact，出现在右侧列表
- 点击列表中任一项 → 上方展示区打开对应内容
- 系统根据数据类型自动选择查看方式
- 同一份数据支持多种查看方式时，展示区右上角可切换
- 可关闭回到列表视图
- 对话区和 Artifact 区独立滚动

### 13.3 数据类型 → 查看方式

| 数据类型 | 默认查看方式 | 备选方式 |
|---------|------------|---------|
| .vtm / 网格数据 | VTK.js 3D 渲染 | — |
| .csv / 表格数据 | 数据表格 | 图表 |
| .png / 图片 | 图片查看 | — |
| JSON 结果（力矩等） | 格式化卡片展示 | 表格 |
| 文件概要 | 区域/标量概览卡片 | — |

### 13.4 对话与 Artifact 联动

- AI 回复中产生可视化内容 → 自动推到 Artifact
- 用户在 3D 视窗点击某个点 → 坐标发给 AI → AI 调 `calculate(method="probe")`
- 用户在表格中选中某行 → 可直接对该数据发起对话
- AI 说"看云图" → 前端 VTK.js 自动渲染对应数据

### 13.5 VTK.js 3D 视窗

Phase 1 实现 VTK.js 基础 3D 渲染（加载网格 + 标量着色 + 旋转/缩放/平移）。
Phase 4 升级为 VTK.js 高级交互（探针点选 → 自动调 probe、框选区域、对话联动）。

---

## 14. 分析存档（Analysis Archive）

### 14.1 需求

用户在分析过程中可以**主动保存**关键结果，形成工程存档。下次打开同一文件时可查阅历史记录。

**不是 AI 的 Memory**，是用户的工程文档。AI 不会自动写入，只在用户明确要求时才保存。

### 14.2 触发方式

| 触发 | 说明 |
|------|------|
| 用户说"保存这次结果" | AI 将当前分析结果写入存档 |
| 用户说"记录一下" | 同上 |
| 用户说"上次的结果是什么" | AI 读取存档 |
| `loadFile` 时 | 如存档存在，提示用户"该文件有历史分析记录，是否查看？" |

**不会自动写入**：每次 `calculate` 后不自动保存，避免存档膨胀和过时数据。

### 14.3 存储结构

```
D:/XField/data/cgns/               ← 用户数据目录
├── ysy.cgns                       ← 数据文件
└── .chatcfd/                      ← 存档目录（首次保存时创建）
    └── ysy.cgns.archive.json      ← 该文件的分析存档
```

### 14.4 存档格式

```json
{
  "file": "ysy.cgns",
  "file_md5": "a1b2c3d4...",
  "entries": [
    {
      "timestamp": "2026-04-03T10:30:00",
      "method": "force_moment",
      "zone": "wall",
      "params": {"pressure": "Pressure", "density": 1.225, "velocity": 340},
      "result": {"CL": 0.35, "CD": 0.012},
      "note": "来流马赫数 1.0 工况"
    }
  ]
}
```

### 14.5 数据一致性校验

| 场景 | 处理 |
|------|------|
| 文件未修改（md5 匹配） | 正常读取存档 |
| 文件已修改（md5 不匹配） | 提示用户："文件已更新，历史存档可能不适用。是否清除旧存档？" |
| 存档文件不存在 | 正常使用，不提示 |

### 14.6 优势

- **用户主动控制**：不自动写入，不会产生过时数据误导 AI
- **跟着文件走**：存档在数据目录下，拷贝数据时一起走
- **可校验**：通过 md5 检测文件是否变更，防止旧结果对不上新数据
- **可追溯**：保存时的参数和结果都有记录

---

## 15. 工作流兜底 — 反问确认机制

### 15.1 需求

当用户的问题无法匹配到现有工作流时，AI 不应该自己乱试，而是通过反问来确认用户意图并引导到可用能力。

### 15.2 决策流程

```
用户输入
  ↓
匹配 Skill 工作流？
  ├── 是 → 执行对应流程
  └── 否 ↓
      匹配 calculate 的某个 method？
        ├── 是 → 执行 calculate
        └── 否 ↓
            可以通过 extractData 解决？
              ├── 是 → 执行 extractData
              └── 否 ↓
                  需要写代码才能解决？
                    ├── 是 → 向用户描述方案，请求确认（AI Coding）
                    └── 否 ↓
                        超出能力范围 → 告诉用户当前支持什么，建议替代方案
```

### 15.3 反问模板

| 场景 | AI 的反问 |
|------|----------|
| 意图模糊 | "您想分析这个文件的哪个方面？我可以：1) 查看文件概要 2) 计算力和力矩 3) 提取指定区域数据" |
| 参数缺失 | "计算力矩需要参考条件。请提供：来流密度(kg/m³)、来流速度(m/s)、参考面积(m²)" |
| 算法不存在 | "当前没有'压力云图'功能。我可以：1) 提取压力数据到 CSV 2) 编写脚本生成图表（需要您确认）" |
| 区域名不确定 | "该文件包含 3 个区域：solid、far、wall。您想分析哪个区域？" |
| 文件未加载 | "请先告诉我要分析的文件路径，例如：分析 D:/data/ysy.cgns" |

### 15.4 Prompt 中的兜底规则

```
当用户的需求无法直接用现有工具完成时：
1. 不要直接用 run_bash 写代码
2. 先告诉用户当前能做什么
3. 如果写代码可以解决，描述方案并请求确认
4. 如果完全超出能力，坦诚告知
5. 通过提问缩小范围，引导到可用工具
```

---

## 16. 需求洞察日志（Insight Log）

### 16.1 目标

自动记录用户的每次提问及处理结果，分类为"已解决"和"未解决"，为产品迭代提供数据依据。

**回答的核心问题**：用户真正在问什么？我们缺什么能力？下一步该优先做什么？

### 16.2 记录结构

每次用户提问自动记录一条，由 Agent 层写入（不依赖 MCP Server）：

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

### 16.3 resolution 分类

| resolution 值 | 含义 | 说明 |
|--------------|------|------|
| `skill_matched` | Skill 工作流直接命中 | 最理想，一步到位 |
| `tool_resolved` | 通过工具组合解决 | 正常，AI 选对了工具 |
| `params_clarified` | 反问后解决 | AI 缺参数，问了用户后解决 |
| `fallback_coding` | 降级为 AI Coding | 工具能力不够，写了代码 |
| `unresolved` | 未解决 | AI 无法处理，用户放弃或换了问法 |
| `error` | 工具报错 | 工具执行失败 |

### 16.4 存储

```
.chatcfd/
├── insight_log.jsonl          ← 追加写入，每行一条记录（JSONL 格式）
└── insight_summary.json       ← 定期聚合的统计摘要
```

JSONL 格式便于追加写入和逐行分析，不需要读整个文件。

### 16.5 统计摘要（定期聚合）

```json
{
  "period": "2026-04-01 ~ 2026-04-07",
  "total_queries": 156,
  "resolution_stats": {
    "skill_matched": 62,
    "tool_resolved": 45,
    "params_clarified": 23,
    "fallback_coding": 15,
    "unresolved": 8,
    "error": 3
  },
  "top_unresolved": [
    {"pattern": "绘图/画图/可视化", "count": 6, "suggestion": "新增 plot method"},
    {"pattern": "切片/截面", "count": 4, "suggestion": "实现 slice method"},
    {"pattern": "对比/比较", "count": 3, "suggestion": "实现 compare method"}
  ],
  "top_errors": [
    {"error": "pressure scalar not found", "count": 2, "suggestion": "loadFile 时提示可用标量名"}
  ],
  "top_fallback_coding": [
    {"pattern": "导出特定格式", "count": 5, "suggestion": "extractData 增加更多格式支持"},
    {"pattern": "自定义统计", "count": 4, "suggestion": "statistics method 增加百分位数等"}
  ]
}
```

### 16.6 产品迭代闭环

```
用户提问 → Insight Log 记录
                ↓
        定期聚合统计
                ↓
  "未解决"和"降级为Coding"的高频问题
                ↓
     转化为新 method 或新 Skill
                ↓
    下次同样问题 → skill_matched
```

**示例**：
- 统计发现"绘图"相关问题 15 次 fallback_coding → 优先实现 `plot` method
- 统计发现"切片"相关问题 8 次 unresolved → 优先实现 `slice` method
- 统计发现"压力标量找不到"报错 5 次 → 优化 `loadFile` 返回值提示可用标量名

### 16.7 隐私

- 日志存在服务端，不存在用户数据目录
- 云端部署时需脱敏：不记录文件完整路径，只记录文件后缀和大小
- 本地部署时可选关闭

---

## 17. 实施路线

### Phase 1：核心能力（当前 → 可用）

**目标**：完成 MCP Server 架构重构 + 基础前端，让用户在本地通过网页即可体验完整链路：对话分析 + 3D 可视化。后端 6 个工具覆盖文件加载、计算、导出、对比；前端实现对话界面 + Artifact 侧边栏 + VTK.js 基础 3D 渲染。

- [ ] 数据层 PostData 薄封装实现（零拷贝 + writeable=False 保护）
- [ ] 算法插件化目录 `algorithms/`，自动扫描加载
- [ ] DEFAULTS 用 dict，统一返回格式 {type, summary, data, output_files}
- [ ] 6 个 MCP 工具实现（loadFile / calculate / compare / exportData / listFiles / getMethodTemplate）
- [ ] 现有 2 个算法（force_moment / velocity_gradient）迁移到插件
- [ ] 新增 statistics 算法（min/max/mean，不依赖 VTK）
- [ ] 会话缓存机制（SessionState + Session Manager）
- [ ] MCP Prompt（Skill 工作流引导）
- [ ] AI Coding 确认机制（Harness 层拦截）
- [ ] Web 前端（对话界面 + Artifact 侧边栏）
- [ ] VTK.js 基础 3D 渲染（加载网格 + 标量着色 + 旋转/缩放/平移）
- [ ] Artifact 展示：3D 视窗 + JSON 卡片 + 数据表格
- [ ] 修复所有已知 bug

### Phase 2：云端 Demo（可用 → 可展示）

**目标**：将 Phase 1 的本地产物部署到云端，让用户打开网页就能体验 ChatCFD。预置典型 CFD 算例供试用，核心是让潜在客户和非技术人员能在 5 分钟内感受到产品价值，不需要安装任何软件。

- [ ] 云端部署 MCP Server + Agent 服务
- [ ] 预置示例数据（3-5 个典型算例）
- [ ] 文件白名单安全机制
- [ ] 分析存档功能（用户主动保存 + md5 校验）
- [ ] 需求洞察日志（Insight Log 记录 + 统计聚合）
- [ ] 用户上传文件（可选）

### Phase 3：算法扩展 + 子 Agent（可展示 → 实用）

**目标**：补齐仿真工程师日常后处理所需的核心算法（切片、流线、等值面、探针、云图渲染），引入子 Agent 处理多文件对比和 AI Coding 等复杂场景。此阶段完成后，ChatCFD 能覆盖 80% 的常规后处理需求，用户可以用它替代传统后处理软件完成大部分工作。

- [ ] 切片（slice）— 依赖 VTK SliceFilter
- [ ] 流线（streamline）— 依赖 VTK VectorFlowLineFilter
- [ ] 等值面（contour）— 依赖 VTK ContourPlaneFilter
- [ ] 表面提取（surface_extract）— 依赖 VTK SurfaceFilter
- [ ] 空间探针（probe）— 依赖 VTK
- [ ] 离屏渲染云图（render）— 依赖 VTK
- [ ] compare 多文件对比 — 子 Agent 隔离上下文
- [ ] 子 Agent：AI Coding 隔离执行
- [ ] 子 Agent：完整报告生成
- [ ] 绘图能力（matplotlib 生成图片 → Artifact 展示）

### Phase 4：产品化（实用 → 商用）

**目标**：支撑多用户并发使用，Artifact 升级为 VTK.js 交互式 3D 可视化，实现对话与 3D 视窗的深度联动。支持混合部署模式（云端 LLM + 本地数据处理），让企业客户的数据不离开内网。基于 Insight Log 的数据持续优化工作流和算法覆盖。

- [ ] 多用户支持 + 会话隔离
- [ ] 混合部署模式（云端 LLM + 本地数据处理）
- [ ] VTK.js 高级功能：探针点选 → 自动调 probe、框选区域、标量切换
- [ ] 对话与 3D 视窗深度联动（AI 说"看云图" → 自动渲染）
- [ ] 结果报告自动生成
- [ ] 反问确认机制优化（基于 Insight Log 迭代）

---

## 18. 测试用例

每个 Phase 完成后，用以下测试问题验证。格式：`用户输入 → 期望行为 → 预期输出`。

### 18.1 Phase 1 测试用例

#### T1.1 文件加载

| # | 用户输入 | 期望调用 | 预期输出 |
|---|---------|---------|---------|
| 1 | "分析 D:/XField/data/cgns/ysy.cgns" | `loadFile(file_path="D:/XField/data/cgns/ysy.cgns")` | 文件概要：3 个区域(solid/far/wall)，403035 单元，81620 顶点，1 个时间步 |
| 2 | "分析 hr.plt" | `loadFile(file_path="hr.plt")` | 自动拼接目录或提示需要完整路径 |
| 3 | "分析 不存在的文件.cgns" | `loadFile(...)` | `{"error": "file not found: ..."}` |
| 4 | "这个目录下有什么文件" | `listFiles()` | 列出当前目录下的文件列表 |
| 5 | "有哪些 plt 文件" | `listFiles(suffix=".plt")` | 只列出 .plt 文件 |

#### T1.2 力矩计算

| # | 用户输入 | 期望调用 | 预期输出 |
|---|---------|---------|---------|
| 6 | "算力和力矩" | `calculate(method="force_moment")` | force{x,y,z} + moment{x,y,z}，不含系数（因为没给参考条件） |
| 7 | "算 wall 区域的力矩" | `calculate(method="force_moment", zoneName="wall")` | 只算 wall 区域 |
| 8 | "升力系数是多少，来流密度 1.225，速度 340，参考面积 1.0" | `calculate(method="force_moment", params='{"density":1.225,"velocity":340,"refArea":1.0}')` | 包含 coefficients（CL/CD 等） |
| 9 | "算力矩"（未加载文件） | `calculate(...)` | `{"error": "No file loaded. Please provide file_path."}` |

#### T1.3 速度梯度

| # | 用户输入 | 期望调用 | 预期输出 |
|---|---------|---------|---------|
| 10 | "计算涡量" | `calculate(method="velocity_gradient")` | `{"result": "OK", "output_file": "...VelocityGradient/res.vtm"}` |
| 11 | "算马赫数和压力系数" | `calculate(method="velocity_gradient", params='{"mach_switch":true,"pressure_coefficient_switch":true}')` | 输出文件路径 |

#### T1.4 统计与提取

| # | 用户输入 | 期望调用 | 预期输出 |
|---|---------|---------|---------|
| 12 | "wall 区域的压力范围" | `calculate(method="statistics")` 或 `extractData(zone="wall", scalars=["Pressure"])` | min/max/mean/std |
| 13 | "导出 wall 的压力和温度到 CSV" | `extractData(zone="wall", scalars=["Pressure","Temperature"], format="csv")` | CSV 文件路径 |
| 14 | "导出所有区域数据" | `extractData(format="csv")` | CSV 文件路径 |

#### T1.5 参数查询

| # | 用户输入 | 期望调用 | 预期输出 |
|---|---------|---------|---------|
| 15 | "有哪些计算方法" | `getMethodTemplate()` | 列出所有 method：force_moment, velocity_gradient, statistics |
| 16 | "力矩计算需要什么参数" | `getMethodTemplate(method="force_moment")` | 参数模板：pressure, density, velocity, refArea... |

#### T1.6 会话缓存

| # | 用户输入（按顺序） | 期望行为 | 验证点 |
|---|-------------------|---------|--------|
| 17 | ① "分析 ysy.cgns" ② "算力矩" | ① loadFile ② calculate（不重新加载） | 第二步不触发文件读取 |
| 18 | ① "分析 ysy.cgns" ② "分析 hr.plt" ③ "算力矩" | ② 加载新文件 ③ 用 hr.plt 数据 | 缓存被新文件替换 |

#### T1.7 兜底与确认

| # | 用户输入 | 期望行为 | 预期输出 |
|---|---------|---------|---------|
| 19 | "画一个压力云图" | 不直接写代码，先反问 | "当前没有绘图功能。我可以：1) 提取压力数据到 CSV 2) 编写脚本生成图表（需确认）" |
| 20 | "帮我跑个脚本" | 先确认 | "请描述您需要执行的操作，我会编写脚本供您确认后再执行。" |
| 21 | "分析一下" （无文件名） | 反问 | "请告诉我要分析的文件路径，或者我可以列出当前目录下的文件。" |

#### T1.8 错误处理

| # | 用户输入 | 触发条件 | 预期输出 |
|---|---------|---------|---------|
| 22 | "算力矩" | 文件中没有 Pressure 标量 | `{"error": "pressure scalar 'Pressure' not found in data"}` |
| 23 | "算 abc 区域的力矩" | 区域名不存在 | 提示可用区域列表或降级为全域计算 |
| 24 | "分析 D:\\XField\\data\\ysy.cgns" | 反斜杠路径 | 自动转正斜杠，正常加载 |

### 18.2 Phase 2 测试用例

#### T2.1 云端 Demo

| # | 用户输入 | 预期行为 | 验证点 |
|---|---------|---------|--------|
| 25 | "有哪些示例数据" | listFiles 列出示例目录 | 返回预置文件列表 |
| 26 | "分析 ysy.cgns 的力矩" | loadFile + calculate | 全流程跑通，结果正确 |
| 27 | "分析 /etc/passwd" | Harness 拦截 | 路径不在白名单，拒绝 |
| 28 | 上传 50MB 文件 | 正常加载 | 上传 + 分析成功 |
| 29 | 上传 2GB 文件 | Harness 拦截 | 超过大小限制，拒绝 |

#### T2.2 分析存档

| # | 用户输入（按顺序） | 预期行为 | 验证点 |
|---|-------------------|---------|--------|
| 30 | ① "分析 ysy.cgns" ② "算力矩" ③ "保存这次结果" ④ 关闭会话 ⑤ 新会话"分析 ysy.cgns" | ③ 写入存档 ⑤ 提示有历史存档 | `.chatcfd/ysy.cgns.archive.json` 存在且内容正确 |
| 31 | "上次的分析结果是什么" | 从存档读取 | 返回保存过的 CL 值和参数 |
| 32 | 修改 ysy.cgns 后再"分析 ysy.cgns" | md5 不匹配，提示用户 | "文件已更新，历史存档可能不适用" |

#### T2.3 需求洞察日志

| # | 用户操作 | 预期记录 | 验证点 |
|---|---------|---------|--------|
| 33 | "分析 ysy.cgns" → loadFile 成功 | `resolution: "skill_matched"` | insight_log.jsonl 有记录 |
| 34 | "算力矩" → calculate 成功 | `resolution: "tool_resolved"` | tools_called 包含 calculate |
| 35 | "画压力云图" → 无 method → AI Coding | `resolution: "fallback_coding"` | tags 包含 "visualization" |
| 36 | "做个 FFT 分析" → 完全不支持 | `resolution: "unresolved"` | top_unresolved 统计可见 |
| 37 | 跑完一周后查看 insight_summary.json | 聚合统计正确 | top_unresolved 列出高频未解决问题 |

### 18.3 Phase 2 补充测试（compare / Artifact / 统一返回格式）

#### T2.4 compare 工具

| # | 用户输入 | 期望调用 | 预期输出 |
|---|---------|---------|---------|
| 38 | "对比 wall 和 far 区域的压力" | `compare(source_a="wall:Pressure", source_b="far:Pressure")` | 差异摘要：max_diff, mean_diff |
| 39 | "把 wall 压力和 experiment.csv 对比" | `compare(source_a="wall:Pressure", file_b="experiment.csv", column_b="Cp")` | 差异摘要 + 差异数据 |

#### T2.5 Artifact 展示

| # | 操作 | 预期行为 | 验证点 |
|---|------|---------|--------|
| 40 | loadFile 后 | 右侧 Artifact 列表出现"文件概要" | 点击可查看 JSON 卡片 |
| 41 | calculate 力矩后 | 列表出现"力矩结果" | 点击可查看格式化结果 |
| 42 | exportData 导出 CSV 后 | 列表出现 CSV 文件 | 点击可查看数据表格 |
| 43 | 同一 CSV 支持表格和图表 | 展示区右上角有切换按钮 | 可在表格/图表间切换 |

#### T2.6 统一返回格式

| # | 调用 | 验证点 |
|---|------|--------|
| 44 | `calculate(method="force_moment")` | 返回含 type="numerical" + summary 一句话 |
| 45 | `calculate(method="velocity_gradient")` | 返回含 type="file" + summary + output_files |
| 46 | `exportData(zone="wall", format="csv")` | 返回含 type="file" + summary + output_files |
| 47 | `compare(...)` | 返回含 type="numerical" + summary |

### 18.4 Phase 3 测试用例

#### T3.1 算法扩展

| # | 用户输入 | 期望调用 | 预期输出 |
|---|---------|---------|---------|
| 48 | "在 x=5 处做一个切片" | `calculate(method="slice", params='{"position":5,"direction":"x"}')` | summary + output_files |
| 49 | "生成流线" | `calculate(method="streamline")` | summary + output_files |
| 50 | "提取等值面，Pressure=100000" | `calculate(method="contour", params='{"scalar":"Pressure","value":100000}')` | summary + output_files |
| 51 | "看 wall 区域的压力云图" | `calculate(method="render", params='{"zone":"wall","scalar":"Pressure"}')` | PNG 图片路径 → Artifact 展示 |

#### T3.2 子 Agent

| # | 用户输入 | 预期行为 | 验证点 |
|---|---------|---------|--------|
| 52 | "对比 ysy.cgns 和 abc.cgns 的压力差异" | 主 Agent 创建子 Agent | 子 Agent 独立加载两个文件，主上下文 token 不爆 |
| 53 | "画 wall 沿 x 的 Cp 分布"（AI Coding） | 主 Agent 创建子 Agent 执行脚本 | 脚本中间输出不污染主对话 |
| 54 | "给我一份完整的分析报告" | 主 Agent 创建子 Agent 多步分析 | 只返回最终报告摘要 |

#### T3.3 算法插件化

| # | 操作 | 预期行为 | 验证点 |
|---|------|---------|--------|
| 55 | 在 algorithms/ 放入 new_algo.py 并重启 | getMethodTemplate() 列出新算法 | 自动扫描加载 |
| 56 | 调用 calculate(method="new_algo") | 正常执行 | 无需改其他代码 |

### 18.5 回归测试检查项

每次改动后必须验证的最小集合：

| # | 测试 | 验证什么 |
|---|------|---------|
| R1 | `loadFile("D:/XField/data/cgns/ysy.cgns")` | 文件加载 + 缓存正常 |
| R2 | `calculate(method="force_moment")` | 力矩计算 + 统一返回格式 |
| R3 | `calculate(method="velocity_gradient")` | 速度梯度 + output_files |
| R4 | `compare(source_a="wall:Pressure", source_b="far:Pressure")` | 对比 + 统一返回格式 |
| R5 | `exportData(zone="wall", format="csv")` | 导出 + 统一返回格式 |
| R6 | `getMethodTemplate()` | 列出所有 method（含插件） |
| R7 | `listFiles(suffix=".cgns")` | 文件列表正常 |
| R8 | 未加载文件直接 calculate | 返回 error dict，不崩溃 |
| R9 | 错误路径 loadFile | 返回 error dict，不崩溃 |
| R10 | 所有返回值含 type + summary | 统一返回格式验证 |

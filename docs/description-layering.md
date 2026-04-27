# ChatCFD 描述分层原则与迭代方法

> 本文记录 ChatCFD 中"工具描述"相关的设计原则、当前现状、重构方向和批判性分析。
> 面向对象：需要改 skills.py / MCP tool docstring / algorithm DESCRIPTION 的开发者。

## 1. 背景

ChatCFD 是 Agent 驱动的产品。LLM 的行为质量**高度依赖**它"读到什么描述"。
描述散落在至少 **7 个位置**：

| # | 层 | 文件位置 | LLM 默认可见 |
|---|---|---|---|
| 1 | 系统 prompt ROLE | `agent/skills.py` | ✅ 每轮都传 |
| 2 | 系统 prompt TOOLS 块 | `agent/skills.py` | ✅ 每轮都传 |
| 3 | 系统 prompt RULES 块 | `agent/skills.py` | ✅ 每轮都传 |
| 4 | MCP tool docstring | `post_service/mcp_tools/*.py` | ✅ MCP 协议上报 |
| 5 | MCP tool signature | 同上 | ✅ MCP 协议上报 |
| 6 | Algorithm DESCRIPTION | `post_service/algorithms/*.py` | ⚠️ 仅 `getMethodTemplate` 调用时暴露 |
| 7 | 物理量映射表 | `post_service/config/physical_mapping.json` | ❌ 后端自动用，不给 LLM |

其中 1-3 是可选（skills.py 你主动写的），4-6 是协议/注册表硬性要求。

## 2. 三层分工原则（核心）

每层**只答一个问题**，避免跨层重复：

| 层 | 回答的问题 | 典型内容 |
|---|---|---|
| **skills.py** | **"我该选哪个？"** | 跨工具编排、选型约束（如 zone 类型）、禁止做的事、会话流程 |
| **MCP tool docstring** | **"我该怎么调？"** | 入口契约：参数格式（如 JSON 字符串）、返回结构、和兄弟工具的边界 |
| **Algorithm DESCRIPTION** | **"这个算法是啥？"** | 算法功能、输入约束、参数语义、输出形态、典型/不典型场景 |

### 自检三问

读到一处描述时，问自己：

1. **skills.py 里**：这一行如果不在这，LLM 能知道吗？能 → 挪走；不能 → 保留
2. **MCP docstring 里**：这条换个 method 就过时吗？过时 → 挪到 algorithm DESCRIPTION
3. **algorithm DESCRIPTION 里**：换个 method 这条仍然一样吗？一样 → 挪到 MCP docstring 或 skills.py

## 3. 每层骨架与长度预估

### MCP tool docstring（每个工具 4-8 行）

```
[一句定位 — 这个工具是干啥的]

重要参数约定（如 params 是 JSON 字符串、非 dict）

参数:
    x: [format + 来源]
    y: ...

返回: [JSON 结构]
失败: [错误返回格式 / 自修复提示]
```

### Algorithm DESCRIPTION（每个算法 3-7 行）

```
[做什么。输入约束（zone 类型等）。]
[关键参数名 + 语义 + 默认值行为]
[输出形态（数据结构 / 文件）]
适用：[典型场景]
不适用：[明确排除的场景，帮 LLM 选别的]
```

### skills.py 各区块

- **ROLE**：1 行身份
- **TOOLS** 方法对比表：≤ 15 字/行，字段为 method + zone 约束 + 一句用途
- **RULES**：跨工具/跨方法的硬规则（"几何操作用体 zone"、"流线需速度分量"），single-method 细节移走

### 总量预估（重构后）

| 层 | 当前行数 | 目标行数 | 变化 |
|---|---|---|---|
| skills.py TOOLS | ~25 | ~12 | −13 |
| skills.py RULES（不含记忆）| ~25 | ~20 | −5 |
| MCP docstring × 6 | ~20 | ~40 | +20 |
| Algorithm DESC × 11 | ~11 | ~55 | +44 |

**关键洞察 — token 成本不是简单"搬来搬去"**：

- skills.py 每轮都传 → 减 1 行 = 每轮省 tokens
- MCP docstring 每轮进 tool schema → 增 1 行 = 每轮费 tokens
- Algorithm DESCRIPTION **仅 `getMethodTemplate` 调用时传** → 0 常规开销

净效果：skills 瘦身 + docstring 膨胀大致相抵；algorithm 扩充是"近乎免费"的信息增量，只有 LLM 主动查时才计费。

## 4. 重构后的风险（批判性分析）

### 风险 1：LLM 选工具时看不到算法约束

如果把"需要体 zone"、"需要速度分量名" 全部搬到 algorithm DESCRIPTION，LLM 选 method 之前看不到，可能先选错再失败重试。

**对策**：skills.py 的 method 表**保留 zone 列**和"跨 method 共性约束"（ChatCFD 当前选择：保留）。只有 method 专属的参数细节（如 direction=0/1/2 映射）才下沉。

### 风险 2：getMethodTemplate 调用频率上升

Algorithm DESCRIPTION 只有调 getMethodTemplate 时暴露。LLM 不查就不知道细节 → 多一轮调用。如果养成每次必查习惯，反而浪费。

**对策**：在 calculate 的 docstring 里**强提示**："不确定参数先调 getMethodTemplate"，鼓励按需查而非盲查。

### 风险 3：重名冲突（架构层面，描述治不了）

`algorithms/compare.py` 和 `mcp_tools/compare.py` 都叫 compare，做相似的事。
**无论怎么写描述，LLM 都会混淆**。

**对策（当前项目采用 Plan C）**：
- 保留两个入口，但**改名拉开语义**
- MCP tool: `compare` → `diffZones`（快速入口：所有共同标量对比，2 参数）
- Algorithm: 保留 `compare`（深度入口：单标量、可定制，通过 `calculate(method='compare', ...)` 调）

### 风险 4：多头维护新冗余

升级 algorithm DESCRIPTION 时容易写进"calculate 怎么调"这种**入口信息** → 又跟 calculate docstring 冗余。

**规则**：
- Algorithm DESCRIPTION **不**提 calculate、不提 MCP 返回格式
- 只说**本算法自己的事**

### 风险 5：RULES 瘦身的软风险

搬走 RULES 里的 algorithm 特定条目后，LLM 在构造 calculate 调用时看不到这些 hint，可能传错参数，靠 `{"error": "..."}` 返回学习。

**对策**：接受"允许一轮失败+自修复"，前提是 algorithm 的错误消息要写得**自解释**（告诉 LLM 哪个参数错、应该传什么）。若追求零失败，则必须在 skills.py 保留该条。

ChatCFD 当前选择：**skills.py 写全**（零失败成本 > token 节省）。

## 5. 描述迭代的三档（改动成本）

修改描述时，要区分**实际影响范围**：

| 档 | 改什么 | 影响文件数 | 典型例子 |
|---|---|---|---|
| **A 纯文字润色** | 只改 docstring 文字，不引入新语义 | 1 | 把 "Compare data" 改成 "对比两个 zone 的所有同名标量" |
| **B 参数语义变** | 文字改了，但引入新格式约定，后端要配合 | 2-3 | docstring 说 "source_a 用 'file:zone' 格式"，engine 要加解析 |
| **C signature 变** | 参数列表改（加/删/改类型） | 3-4 | `source_a: str` → `source_a: dict` |

**原则**：先做档 A，档 A 不够用的**证据**出现后才升档 B，档 B 跑稳才升档 C。**不跳级**。

## 6. 反馈闭环

描述改得好不好，用**真实对话 trace** 验证，不靠感觉。

### 数据采集（passive）

- 每轮结束时将 `session.messages` dump 到 `.chatcfd/traces/{conv_id}.json`
- 零侵入主路径，只作为副作用写盘

### 离线分析

- `tools/analyze_traces.py` 扫所有 trace，每用户轮一行 CSV
- 关键列：`tools_called`、`next_user_query`、`correction_flag`（下一轮是否疑似纠正）
- 输出按工具聚合的"调用次数 vs 被纠正次数"表

### 症状 → 改哪一层的映射

| 症状（从 CSV 里看到的） | 病因 | 改哪里 |
|---|---|---|
| 用户说"画切片"，LLM 没调 calculate | 工具入口描述不清 | **skills.py** TOOLS 表 / **calculate.py** docstring |
| 选对 calculate 但 method 名乱填 | method 列表 LLM 不知道 | **skills.py** method 表 补全 |
| method 选对但参数传错（如 "Y 方向" → direction=0）| 参数语义不明 | **skills.py** RULES / **algorithm** DESCRIPTION |
| zone 用错了（体用成面/反之）| zone 约束不显眼 | **skills.py** method 表 zone 列 / RULES |
| LLM 反复调 getMethodTemplate | 信息暴露不够 | **algorithm** DESCRIPTION 写详细 |
| 用户意图一致但换说法触发不同工具 | 工具边界模糊 | **架构决策**：改分类或重命名 |
| RULES 里写了但 LLM 还是踩坑 | 规则被噪音淹没 | **skills.py** RULES 措辞强化 / 顺序 / 合并 |

### 记录改前/改后（不用额外基础设施）

- 档 1：`git log -p agent/skills.py` 天然是改动历史
- 档 2：改之前跑 3-5 条代表性 query，把对话结果存到 `docs/regression/before_YYYYMMDD.md`；改之后跑同样 query 存 `after_*.md`；肉眼对比
- 档 3（可选）：trace JSON 里存 git commit hash，CSV 分析时按 commit 分组

## 7. 当前 pilot 状态

以下改动已落地，用作风格验证：

### 结构重命名
- `mcp_tools/compare.py` → `diffZones`（Plan C：拉开与 `calculate(method='compare')` 的语义）
- `diffZones` 是"快速全标量对比"入口，`calculate(method='compare')` 是"定制单标量对比"入口

### 描述升级
- `mcp_tools/calculate.py` docstring：从 1 行 → 约 15 行。明确 `params` 是 JSON 字符串、失败重试思路
- `mcp_tools/compare.py`（现 diffZones）docstring：定位清晰、划清边界
- `algorithms/rtslice.py` DESCRIPTION：从 1 行 → 7 行。含 zone 约束、direction 映射、默认行为、适用/不适用
- `algorithms/force_moment.py` DESCRIPTION：从 1 行 → 7 行。含必需参数、可选参数、输出、适用/不适用
- `agent/skills.py`：slice 行精简（参数细节下沉到 algorithm）

### 未改动（等 pilot 验证后再铺开）
- 其余 9 个 algorithm 的 DESCRIPTION 仍是一行
- 其余 4 个 MCP tool docstring 仍是一行
- skills.py 的工具清单表、RULES 中的 method-specific 条目（第 7/8 条）暂未动

## 8. 参考资源

- Anthropic "Building Effective Agents" —— 官方 agent 设计原则
- Anthropic Tool Use 文档 —— 工具描述最佳实践
- `CLAUDE.md` —— ChatCFD 项目的"AI 约束三层"约定（Harness > Skill > Prompt）
- `docs/agent-framework-analysis.md` —— Agent 框架选型分析

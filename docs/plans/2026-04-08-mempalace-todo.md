# Mempalace 集成 — 待办事项

> 关联方案：[2026-04-08-mempalace-integration.md](2026-04-08-mempalace-integration.md)
> 创建日期：2026-04-08

---

## Phase M1：最小可用（记忆增强主 Agent）

### 1. 基础设施

- [ ] **M1-1 MCPClientPool 重构**
  - 文件：`agent/mcp_client.py`
  - 将单 server MCPClient 重构为 MCPClientPool
  - 支持 SSE（post_service）+ stdio（mempalace）双协议
  - 实现 tool name → server 路由表（mempalace_ 前缀路由到 mempalace client）
  - 合并 `get_tools_for_llm()` 输出（只包含暴露的工具）
  - 验收：能同时连接两个 MCP server 并调用各自的工具

- [ ] **M1-2 Embedding 模型替换**
  - 为 chatCFD 的 mempalace 实例配置 `bge-small-zh-v1.5`（96MB）
  - 实现 ChromaDB 自定义 EmbeddingFunction
  - 确保在首次 `mempalace init` 时就使用新模型（不能先用默认再换）
  - 验收：中文查询"升力系数"能匹配到包含"升力系数 CL"的 drawer

### 2. 工具暴露与路由

- [ ] **M1-3 工具过滤逻辑**
  - 文件：`agent/mcp_client.py` (MCPClientPool.get_tools_for_llm)
  - 定义暴露白名单：`mempalace_search`, `mempalace_add_drawer`, `mempalace_kg_query`, `mempalace_kg_add`
  - 其余 17 个 mempalace 工具不出现在 LLM 工具列表中
  - 代码层自动调用的工具（如 check_duplicate）通过 MCPClientPool 内部方法直接调用
  - 验收：`get_tools_for_llm()` 返回 10 个工具（6 + 4）

- [ ] **M1-4 add_drawer 自动去重**
  - 在 agent_loop.py 的 tool dispatch 中，拦截 `mempalace_add_drawer` 调用
  - 调用前自动执行 `mempalace_check_duplicate(content, threshold=0.9)`
  - 如果是重复内容，跳过存储并告知 LLM
  - 验收：重复内容不会产生冗余 drawer

### 3. System Prompt 扩展

- [ ] **M1-5 记忆工具使用规则**
  - 文件：`agent/skills.py`
  - 在 SYSTEM_PROMPT_TEMPLATE 中新增记忆工具说明段落
  - 规则要点：
    - 用户说"上次/之前/记得吗" → 调 `mempalace_search`
    - 分析得出重要结论（CL/CD 值、工程发现）→ 调 `mempalace_add_drawer`
    - 不要把每次 calculate 的原始数据都存入记忆
    - 精确计算结果用 Archive 保存，模糊偏好/发现用 mempalace
  - 验收：LLM 在合适时机主动调用记忆工具

- [ ] **M1-6 存储规范写入 prompt**
  - 文件：`agent/skills.py`
  - 规则：存入记忆时物理量必须用「中文全称 + 英文缩写 + 数值」
  - 示例："升力系数 CL=0.45, 阻力系数 CD=0.021, body 参照系"
  - 验收：LLM 存入的 drawer 内容包含中英文双写

### 4. 记忆注入

- [ ] **M1-7 loadFile 后触发记忆检索**
  - 文件：`agent/agent_loop.py`
  - loadFile 工具返回后，自动推断 wing（从文件路径取项目级目录）
  - 代码层调用 `mempalace_search(wing=推断的wing, limit=3)`
  - 如有相关记忆，追加到下一轮 LLM 的 messages 中作为 system 提示
  - 验收：加载同一项目的文件时，LLM 能获取到历史分析记忆

- [ ] **M1-8 全局偏好注入**
  - 文件：`agent/agent_loop.py`
  - 对话首条消息处理前，代码层调用 `mempalace_kg_query(entity="user")`
  - 如有偏好（参照系、单位等），注入 system prompt 末尾
  - 验收：新对话自动获知用户的参照系偏好

### 5. Session 扩展

- [ ] **M1-9 AgentSession 增加记忆字段**
  - 文件：`agent/session.py`
  - 新增字段：`memory_wing: str | None`, `loaded_file_path: str | None`
  - loadFile 成功后自动填充
  - 验收：后续工具调用能获取当前 wing 信息

---

## Phase M2：智能记忆

### 6. Wing 自动推断

- [ ] **M2-1 文件路径 → Wing 映射规则**
  - 定义路径解析规则：取文件所在目录的上一级作为 wing 名
  - 示例：`D:/XField/NACA0012/case_001.cgns` → wing: `naca0012`
  - 用户可通过对话修正："这个文件属于风洞对标项目" → 更新 wing
  - 验收：不同项目目录下的文件自动归入不同 wing

### 7. Room 选择

- [ ] **M2-2 LLM Room 选择机制**
  - 定义初始 Room 列表：results / parameters / visualization / findings / workflow
  - 在 `mempalace_add_drawer` 的 system prompt 指引中要求 LLM 从列表选择 room
  - 允许 LLM 创建新 room（开放集合），但需给出理由
  - 验收：存入的 drawer 有合理的 room 分类

### 8. 偏好时序管理

- [ ] **M2-3 知识图谱偏好覆盖逻辑**
  - 用户偏好变更时（如参照系从 body 改为 wind）：
    - 代码层自动调用 `mempalace_kg_invalidate` 失效旧三元组
    - 再调用 `mempalace_kg_add` 写入新三元组
  - 验收：`mempalace_kg_query(entity="user")` 只返回当前有效偏好

### 9. 对话结束沉淀

- [ ] **M2-4 对话结束时自动提取结论**
  - WebSocket 断开或用户长时间无操作时
  - 代码层提取本次对话的 artifacts 列表
  - 调用 LLM 判断哪些值得存入记忆（避免每次 calculate 都存）
  - 验收：重要结论自动沉淀，日常操作不产生冗余记忆

---

## Phase M3：子 Agent + Diary

### 10. Coding 子 Agent Diary

- [ ] **M3-1 Coding 子 Agent 接入 diary**
  - 子 Agent 执行完毕后自动调用 `mempalace_diary_write("coding_agent", ...)`
  - 记录：用户需求摘要、使用的库、脚本模式
  - 下次创建 Coding 子 Agent 时，先 `mempalace_diary_read("coding_agent", last_n=5)`
  - 验收：第二次类似绘图需求时，子 Agent 能复用历史脚本模式

### 11. 报告子 Agent Diary

- [ ] **M3-2 报告子 Agent 接入 diary**
  - 记录：报告结构、用户反馈（"太长了"、"缺少图表"）
  - 验收：报告质量随使用次数提升

---

## 技术风险清单

| # | 风险 | 影响 | 缓解 |
|---|------|------|------|
| R1 | bge-small-zh 模型加载增加启动时间 | 首次启动慢 3-5 秒 | 模型文件预下载到部署包 |
| R2 | stdio MCP 子进程管理（崩溃/僵尸进程） | mempalace 服务不可用 | 心跳检测 + 自动重启 |
| R3 | LLM 过度/不足使用记忆工具 | 体验不稳定 | system prompt 迭代 + Insight Log 监控 |
| R4 | 记忆内容过时误导 LLM | 错误结论 | loadFile 后只注入同 wing 记忆；Archive 有 md5 校验 |
| R5 | ChromaDB 持久化目录权限/路径问题（Windows） | 初始化失败 | 启动时检查路径可写性，失败时降级为无记忆模式 |
| R6 | 工具选择准确率下降（10 工具 vs 原 6 工具） | 误调记忆工具 | Insight Log 监控工具选择分布，prompt 迭代 |

---

## 验收标准

### M1 完成标准
1. chatCFD 能同时连接 post_service 和 mempalace 两个 MCP server
2. 用户分析文件后，LLM 在合适时机主动存入记忆
3. 新对话加载同一项目文件时，LLM 能获取历史分析记忆
4. 中文查询能命中中文存储内容
5. 工具总数 ≤ 10，不影响核心工具选择准确率

### M2 完成标准
1. 不同项目文件自动归入不同 wing
2. 用户偏好变更后，旧偏好自动失效
3. 对话结束自动沉淀关键结论，不产生冗余

### M3 完成标准
1. Coding 子 Agent 第二次处理类似需求时能复用历史脚本模式
2. 报告子 Agent 能记住用户对报告格式的反馈

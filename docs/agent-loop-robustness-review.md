# ChatCFD Agent Loop 健壮性问题诊断与复盘

**日期**：2026-04-17
**作用域**：`agent/agent_loop.py`、`agent/session.py`、`agent/harness.py`
**触发**：参考 HermesAgent (NousResearch) 设计，反思 ChatCFD agent loop 的潜在健壮性问题

---

## 一、问题描述

### 问题 1：Context 累积爆炸

**现象**

`agent/agent_loop.py:187, 314` 每轮调 LLM 用 `[system_msg] + session.messages`，而 `session.messages` 在 4 处被 append（L197, L280, L374, L476）只增不减。

**根因**

缺少 context 生命周期管理。`harness.after_call` 截单次结果，但累积无人管。

**影响**

- 用户连续做 10-15 轮 CFD 分析（典型工作量），context 撑爆模型窗口
- 触发的错误（"context_overflow"、"maximum context length exceeded"）不在 `agent_loop.py:192-195` 识别的关键字里 → 直接挂掉，用户分析进度全丢
- 即使没爆，长 context 让推理速度线性下降、费用线性上升

---

### 问题 2：持久化层缺失

**现象**

`session.py:21-23` `SessionPool` 是纯内存 dict。进程重启 → 所有会话蒸发。

**根因**

项目尚处 Phase 1，会话持久化未列入需求。

**影响**

- 当前：刷新浏览器 / 服务重启 / 容器重新部署 → 用户分析上下文丢失
- 未来：一旦加持久化，不做原子写就会出现"半截写入"破坏 JSON / Mempalace 节点

---

### 问题 3：硬截断 + 错误识别窄

**现象 A**：`max_rounds=10` (`agent_loop.py:168, 290`) 到点直接 "Maximum rounds reached"，不区分"出错卡住"还是"任务即将完成"。

**现象 B**：错误分类只识别 4 个关键字（quota/balance/insufficient/rate）。`context_overflow`、`model_not_found`、临时网络抖动、上游 504 等都走默认分支 → 无重试、无降级、直接报错给用户。

**影响**

复杂分析任务（10+ 轮的对比分析、多算例汇总）跑不完；用户体验差；偶发错误无自愈能力。

---

## 二、解决方案（设计思路，无代码）

### 方案 1：分层 Context 管理

| 层 | 内容 | 何时触发 |
|---|---|---|
| L0 完整保留 | system prompt + 最近 3-5 轮 | 永远 |
| L1 摘要替代 | 中间轮的 tool result | token 预算 > 70% |
| L2 结构化档案 | 老会话的关键产物（已加载文件、已算指标） | token 预算 > 85% |

**关键设计点**：

- 触发用 token 预算而非轮数（轮数会因工具结果大小波动）
- 摘要素材**复用 `_make_artifact_title` 已有的人类可读标题**——比再调 LLM 摘要快、准、零成本
- 用便宜模型做摘要（qwen-turbo / gemini-flash）

### 方案 2：写盘原则（不依赖现在有没有持久化）

**立刻做**：建立一个 `atomic_write_json(path, data)` 工具函数，全项目禁止裸 `open(w)`。代价：1 小时。

**做完后**：未来加任何持久化，自动用上原子写，不需要回头补。

**JSONL 文件**（如 insight_log）：append + flush + fsync，天然适合追加场景。

### 方案 3：错误分类 + 弹性预算

**错误分类枚举**（参考但不照搬 HermesAgent）：

```
ContextOverflow → 触发压缩，重试一次
RateLimit → 等 1-3 秒重试，最多 3 次
QuotaExceeded → 不重试，给用户清晰提示
ModelNotFound → 切换到备用模型
TransientNetwork → 立即重试 1 次
Unknown → 给用户错误信息 + 上报日志
```

**弹性预算**：

- 软阈值（8 轮）：开始警告 + 触发 context 压缩
- 硬阈值（15 轮）：让 LLM 写"目前进度 + 推荐下一步"，给用户可继续的出口
- 不要在 round=10 直接 "Maximum rounds reached" 这种死局

---

## 三、批判性复盘：这些真的是当前最该解决的吗？

### 反问 1：用户实际会话有多长？

我假设的是"10-15 轮典型会话"，但**这是猜的，没数据**。

真实情况可能是：

- 如果 CFD 分析多数 3-5 轮就结束 → ContextCompressor 是**过度工程**，先做"清空工具结果 data 字段"这种 5 行代码的便宜方案就够
- 如果用户经常 15-30 轮 → 那它真的是高优
- 如果你目前用户量很小（Phase 1），你其实没数据支撑这个判断

**建议**：**先加埋点**——记录每次 `session.messages` 的 token 数和轮数，跑一周看真实分布，再决定要不要做 ContextCompressor。**没数据时优先做埋点，而不是优先做优化。**

### 反问 2：持久化层"未来问题"现在该花多少精力？

建议"建立 atomic_write_json 工具函数"是 1 小时投入，这个 ROI 高，可以做。

但**不要现在就设计完整的会话持久化方案** —— 这是典型的 YAGNI 陷阱。Phase 1 阶段，"刷新浏览器丢会话"对单用户调试场景不是大问题；等真正有多用户/长会话需求再设计也不晚。

### 反问 3：max_rounds=10 真的是 bug 吗？

可能不是 bug，可能是**正确的设计**：

- CFD 分析任务多数应该 5-8 轮内完成
- 超过 10 轮通常意味着 agent 卡了 / 用户问题不清晰 / 工具不够用
- "硬上限 + 用户重新组织问题"可能比"agent 自己再尝试 5 轮"更合理

**比 max_rounds 更值得改的是错误识别**——那 4 个关键字真的窄了，遇到 context overflow 直接挂是真 bug。

### 反问 4：是不是有点 cargo culting？

老实讲：**有**。HermesAgent 是 Nous Research 投了大量人力的明星项目，看起来 fancy 的东西很多。但 ChatCFD 跟它的**问题域完全不同**：

| HermesAgent 解决的问题 | ChatCFD 实际场景 |
|---|---|
| 跨平台 agent (Telegram/Discord/Slack) | Web WebSocket，单一通道 |
| 多用户、多会话、跨设备记忆 | 单用户调试场景 |
| 自学习 skill（agent 自己写新工具） | 工具固定（6 个 MCP），不允许自演化 |
| RL 训练数据采集 | 应用层，不需要 |
| 长期常驻 agent，记住用户习惯 | 单次 CFD 分析任务，结束即关 |

**结论**：HermesAgent 的很多设计是为它的问题域服务的，搬到 ChatCFD 反而是负担。

---

## 四、HermesAgent 到底能给 ChatCFD 带来什么（诚实账本）

### ✅ 真值得借鉴（少而精）

| 项 | 价值 | 投入 |
|---|---|---|
| **错误分类思想** | 把 4 个关键字升级到 6-8 个语义类型 + 对应恢复策略 | 1-2 天 |
| **原子写约束** | 一个工具函数 + 全项目纪律 | 1 小时 |
| **Token 预算管理 + 弹性触发** | 比硬轮数上限更智能 | 跟下面合并做 |

### ⚠️ 看起来酷但要谨慎

| 项 | 真实价值 | 注意 |
|---|---|---|
| **ContextCompressor** | 中。**先加埋点**确认用户真的需要再做 | 否则是过度工程 |
| **细粒度 callback 系统** | 中。已经有 `tool_start` / `tool_result` / `token` 三种事件，够用 | HermesAgent 10+ 种是为 Discord/Telegram 多消费者设计的 |
| **AST 工具自注册** | 低。6 个 MCP 工具手工注册不累 | 等到 30+ 工具再考虑 |

### ❌ 不该借鉴

- 自学习 skill（工具集是固定的）
- 多平台 Gateway（是 Web 单通道）
- ACP adapter / RL 训练（无关）
- 600KB 单文件架构（反模式）

### 🎁 ChatCFD 已经做得比 HermesAgent 好的

老实说几个：

1. **三层 AI 约束（Harness/Skill/Prompt）** —— `CLAUDE.md` 写的"硬约束三层"比 HermesAgent 那种 prompt 堆 system message 干净
2. **Artifact + summary 双通道** —— LLM 看 summary 小数据，前端拿 raw 大数据走 HTTP API。HermesAgent 没有这种分离，所有数据都过 LLM
3. **Mempalace 知识图谱（结构化记忆）** —— 比 HermesAgent 的 MEMORY.md（纯文本 + 2200 字符硬上限）先进
4. **`_make_artifact_title` 这种语义标题生成** —— HermesAgent 没有，工具结果在历史里只有 raw JSON

---

## 五、修订后的行动建议（按 ROI 重排）

| # | 动作 | 投入 | 价值 |
|---|---|---|---|
| 1 | **加埋点**：记录 session.messages 的 token 数和轮数分布 | 2 小时 | 决定后续要不要做 ContextCompressor |
| 2 | **错误分类升级**：6-8 个错误类型 + 对应恢复策略 | 1-2 天 | 立刻提升健壮性 |
| 3 | **建立 `atomic_write_json` 工具函数 + 项目纪律** | 1 小时 | 一次投入，长期受益 |
| 4 | **改 max_rounds 死局**："Maximum rounds" 改成"已做 X，建议 Y" | 半天 | 用户体验立刻改善 |
| 5 | **观望 1 周埋点数据**，再决定 ContextCompressor | — | 数据驱动 |

**核心结论**：HermesAgent 给 ChatCFD 的真实价值是**少数几个机制 + 反面教训**，不是大规模代码移植。原本的"高优先级 ContextCompressor"应降级为"先观察再决定"。

---

## 附录：相关文件位置

- ChatCFD agent loop：`agent/agent_loop.py`
- ChatCFD session：`agent/session.py`
- ChatCFD harness：`agent/harness.py`
- HermesAgent 错误分类：`hermes-agent/agent/error_classifier.py:24-58`（参考来源）
- HermesAgent ContextCompressor：`hermes-agent/agent/context_compressor.py:188+`（参考来源）
- HermesAgent IterationBudget：`hermes-agent/run_agent.py:170-212`（参考来源）

# ChatCFD 实际对话会话问题汇总（2026-04-17 ~ 2026-04-19）

整理本次开发期间，用户在 ChatCFD 对话窗里向 LLM 提的问题/请求，以及实际表现暴露的问题。

---

## 1. 文件加载

### 用户提问
- "加载 D:/XField/data/cgns/ 下的 x37b 文件"
- "做模糊查询 x37b"
- "加载 x37b"
- "D:\\XField\\data 下的 cgns 文件 x37b"
- "D:/XField/data/cgns/x37b，这个地址是存在的"

### 暴露的问题
| 现象 | 根因 |
|---|---|
| LLM 说 "File not found" | LLM **猜文件名**（用户说 `x37b` 但实际叫 `x37b-02.cgns`）|
| LLM 反问 "请确认完整路径" | 不会自己用 `listFiles` 搜索 |
| LLM 拒绝加载 .py 源码 | loadFile 文档明确只支持 CFD 格式，LLM 判断正确但表达让用户困惑 |
| 第一次 listFiles 扫了 15 秒 | 从 `D:/XField` 根目录递归全盘扫，没有上限 |

### 改动
- skills 加规则：不确定文件名时先 `listFiles(recursive=true, keyword=...)` 搜
- listFiles 加 `recursive` + `keyword` + 200 条上限

---

## 2. GIF 动画生成（本次会话最大痛点，迭代 10+ 次）

### 用户提问演变
1. "将这 5 个切片合成 GIF 动画"
2. "我想看一堆的切片组合成的 gif 图"
3. "加载 x37b，沿 X 方向切 10 个切片，用涡量着色，合成 GIF 动画"
4. "加载 x37b，切 10 个切片做 GIF"
5. "能直接切片完就直接出图呢？"

### 失败链路（发生在用户对话里）

```
用户: "合成GIF" 
LLM: 调 calculate(slice, n_slices=10) → 1个VTP（10个平面合并）✅
LLM: "确认执行 Python？" 
用户: "确认"
LLM: runPython → 语法错误（多行字符串没闭合）
LLM: "切换方案"
LLM: runPython → imageio 没装  
LLM: "用 magick"
LLM: runBash("magick ...") → 命令未找到
LLM: "用 PIL"
LLM: runPython → 终于成功  
用户: "右边看不到 GIF"
LLM: ❌ 反复推荐用户自己下载本地查看
```

### 暴露的问题
| 现象 | 根因 |
|---|---|
| 同一任务 4 次反复确认 | skills 规则太严，每步都问 |
| 三次 runPython 失败 | tool description 写了 `imageio` 实际没装；LLM 不知道环境真实情况 |
| LLM 声称 "20 帧 PNG 已生成"但实际没有 | LLM 幻觉，没看 output_files |
| GIF 生成了但 artifact 不显示 | type=image 被 ArtifactPanel 过滤 |
| 10 张 PNG 合在一张图里（"我想要一张一张"）| slice 输出合并 VTP，render 当一个 polydata 处理 |
| GIF 是黑的 | 渲染时相机角度斜着看薄平面，看到的是一条线 |
| 合成 GIF 要 12 次 MCP 调用 | slice + render×10 + runPython 太复杂 |

### 改动
- runPython tool description 改为**启动时动态检测**可用库
- skills 加规则："禁止声称已完成而未验证 output_files"
- skills 加规则："一次确认覆盖整个任务，不要每步都问"
- ArtifactPanel 加 `image` 类型 + `.gif` 扩展支持
- 路径规范化（反斜杠 → 正斜杠）
- slice 算法加 `output_images=True`：**一步出 PNG 序列 + GIF**
- 切片渲染相机正对平面（按 direction 设位置）
- GIF 自动作为单独 artifact 推送

---

## 3. 用户确认与卡死

### 用户提问
- "确认"（出现 5+ 次）
- "确认执行"
- "确认合成"
- "标志状态的图标怎么没有了？卡住了"
- "什么都没有"（指 Agent 窗口无日志）

### 暴露的问题
| 现象 | 根因 |
|---|---|
| 反复要求"确认" | skills 没说"一次确认覆盖整个任务" |
| 第一次 runPython 调用 2ms 就返回 | Harness 拦截（user_confirmed_coding=False）但 LLM 没意识到，反复重试 |
| LLM 输出 "正在执行Python代码生成Cp对比曲线图..." 然后卡死 | qwen-plus 只输出文字 narration，没真的发出 tool_call |

### 改动
- skills 规则："一次确认覆盖相关任务，失败重试不需重新确认"
- skills 规则："禁止只说正在执行而不真的调工具"
- main.py 加用户确认关键词检测（"可以/确认/执行" 等触发 `user_confirmed_coding=True`）
- agent_loop 加 `tool_pending` 事件，LLM 生成 tool_call 时立即推送前端"正在准备 runPython..."（带旋转 spinner）
- agent_loop 加 `[Timing]` 日志（LLM 推理 + MCP 调用耗时）

---

## 4. 右侧 Artifact 显示

### 用户提问
- "没法在右侧 artifact 看 为什么？"
- "GIF 生成了但是没有在右侧显示"
- "还是显示这个"（JsonCard 而非图片）
- "这样"（碎图标）
- "标志状态的图标怎么没有了？"
- "右侧 artifact 中能显示哪些内容？gif 好像不可以呢"
- "这个多了后就乱了"（tab 累积）

### 暴露的问题
| 现象 | 根因 |
|---|---|
| GIF tab 出现但内容是 JSON | viewerType 判断条件漏 `image` 类型 |
| 改完 viewerType 后还是 JsonCard | 过滤器（filter）也漏 `image` 类型 |
| 加了 image 后是碎图标 | 路径有反斜杠，URL 编码失败 |
| 多次跑后 tab 累积 6+ 个 | addArtifact 每次 push，不去重 |

### 改动
- ArtifactPanel filter + viewerType 都加 `image` 类型
- ArtifactPanel filter + viewerType 都加 `.gif` 扩展
- 路径规范化 `\\` → `/`
- addArtifact 同 file_path 覆盖，不重复 push

---

## 5. 性能体感

### 用户提问
- "为什么用 loadfile 有时候加载会很慢"
- "那为啥在对话中读 x37B 差不多要几十秒？"
- "很久了"（loadFile 卡 300 秒）

### 实测结果（直接调 engine.load_file）
| 文件 | 大小 MB | 实际耗时 |
|---|---:|---:|
| ysy.cgns | 62 | 0.20s |
| AOA10.5_mach1.2.cgns | 446 | 0.99s |
| j20_1.cgns | 478 | 1.07s |
| car.cgns | 2,062 | 1.52s |
| x37b-02.cgns | 457 | 1.59s |

**真实链路耗时分解**（在对话中感觉到的"几十秒"）：
- LLM 推理生成 tool_call: 3-15s
- MCP SSE 重新建立连接: 0.5-2s
- engine.load_file 真实计算: 1-2s
- mempalace_search subprocess（已禁用）: 3-10s
- LLM 读结果生成回复: 3-10s

### 改动
- 关闭 loadFile 后的 mempalace 自动注入
- 加 `[Timing]` 日志便于诊断
- 加 `tool_pending` UI 提示，消除"准备 tool_call 时的空窗期"

---

## 6. 演示需求（4 个新爆点）

### 用户提问
- "有什么可以给用户展示 agent 能力的爆点，让人眼前一亮？最好站在工程师的角度"
- "你说的这 5 个点 现在都能做吗？"
- "把曲线数据分布、自动报告、方案对比、仿真检查这些都做进去吧"

### 已实现
| 功能 | 用法（用户对话） |
|---|---|
| **线数据曲线** | "给我翼根到翼尖的压力分布曲线" |
| **质量检查** | "检查一下 ysy.cgns 有没有问题" |
| **跨文件对比** | "对比 ysy 和 j20_1 的壁面压力" |
| **自动报告** | "给我出一份 x37b 的完整分析报告" |

---

## 7. 服务管理

### 用户提问
- "要重启吗"（多次）
- "需要重启吗？还是直接刷新前端就可以"
- "是刷新页面就可以吗？还是需要重新计算"
- "上一次的生成了吗"

### 答复模板
| 改了什么 | 是否需要重启 |
|---|---|
| Python 文件（PostService/Agent）| `--reload` 自动重启，无需手动 |
| Vue 组件（前端）| Vite HMR 自动更新，无需刷新 |
| Vue store / 数据结构变更 | 需要刷新页面，且旧 artifact 数据保留旧格式 |
| 改了 skills.py 等 prompt | 需要新开对话（旧对话 LLM 上下文已固化）|

---

## 总结

本次会话最大的痛点不是"能不能做"，而是 **"对话流畅度"**：

| 问题类型 | 表现 |
|---|---|
| LLM 行为不可控 | 反复确认、声称完成未验证、只说不做 |
| 工具能力与文档不符 | tool description 写了不存在的库 |
| 多步流程过度拆分 | 一个 GIF 要 12 次 MCP 调用 |
| 反馈缺失 | 长时间无 UI 更新（tool_call 生成期间空窗）|
| 显示链路碎片 | type/extension/路径任何一个不对都看不到结果 |

**关键改动方向**：
1. **算法层**：把多步操作合成单步（slice + output_images 一步出 GIF）
2. **Skills 层**：约束 LLM 行为（一次确认、说了必做、用现有工具）
3. **传输层**：tool_pending 即时反馈，去掉空窗期
4. **UI 层**：artifact 类型/扩展全覆盖，去重覆盖避免累积

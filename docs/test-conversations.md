# ChatCFD 对话测试清单

每次代码改动后，按这个清单挨个测一遍。每个测试用例标注：**输入 → 预期行为 → 失败时该看什么**。

测试文件目录：`D:/XField/data/cgns/`

---

## 0. 准备工作

```
□ 启动 start.bat（PostService 8001 / Agent 8080 / Web 5173）
□ 浏览器打开 http://localhost:5173
□ F12 → Console 看 WebSocket 是否 Connected
□ 新开对话（不要复用旧 session 避免状态污染）
```

---

## 1. 文件加载（5 个用例）

### 1.1 完整路径加载
**输入**: `加载 D:/XField/data/cgns/ysy.cgns`
**预期**:
- 一次 `loadFile` 调用
- 1-2 秒完成
- 右侧 artifact 出现 "ysy.cgns" tab
- LLM 回复列出 zones / 点数 / 单元数 / cell_types

**失败看**: Agent 窗口 `[Timing]` 日志

---

### 1.2 模糊文件名（递归搜索）
**输入**: `加载 x37b`
**预期**:
- 先调 `listFiles(recursive=true, keyword="x37b")` 搜索
- 找到 `x37b-02.cgns`
- 自动 `loadFile` 完整路径
- 不反问"请确认完整路径"

**失败看**: 是否 LLM 直接猜了 `x37b.cgns` 然后报 File not found

---

### 1.3 不带扩展名
**输入**: `加载 D:/XField/data/cgns/ 下的 x37b 文件`
**预期**: 同 1.2

---

### 1.4 用户给出错误路径
**输入**: `加载 D:/XField/wrong/path.cgns`
**预期**:
- 报 File not found
- 不卡死，不无限重试
- 建议用户检查路径或用 listFiles 浏览

---

### 1.5 加载第二个文件（多文件 session）
**前置**: 1.1 完成
**输入**: `再加载 j20_1.cgns`
**预期**:
- 加载新文件
- 右侧出现两个文件 tab
- 切换 tab 不会丢数据

---

## 2. 基本计算（4 个用例）

### 2.1 标量统计
**输入**: `给我 ysy.cgns 的 solid zone 标量统计`
**预期**:
- 一次 `calculate(method="statistics", zone_name="solid")`
- 回复列出每个标量的 min/max/mean/std

---

### 2.2 切片（不出图）
**输入**: `沿 X 方向切 5 个切片`
**预期**:
- `calculate(method="slice", n_slices=5, direction=0)`
- 右侧 artifact 出现 3D 视图（合并 VTP）
- 左下角 Scalar 下拉框可切物理量

---

### 2.3 流线
**输入**: `画流线`
**预期**:
- `calculate(method="streamline")`，自动用 vtk 引擎
- LLM 从已加载的标量列表里挑速度分量
- 右侧 artifact 出现流线 3D 视图

**失败看**: 如果效果差，发"效果不好" → LLM 应改用 `engine="rt"`

---

### 2.4 力/力矩
**输入**: `算 wall 的升力系数`
**预期**:
- LLM 先反问参考面积/来流条件，**不猜**
- 用户给参数后 → `calculate(method="force_moment", zone_name="wall")`

---

## 3. GIF 动画（最易出问题，重点测）

### 3.1 切片 + GIF 一步到位 ⭐
**输入**: `沿 X 方向切 10 个切片，按涡量着色，合成 GIF 动画`
**预期**:
- LLM **一次** `calculate(method="slice", params={"n_slices":10, "output_images":true, "scalar":"vorticity_mag"})` 调用
- 用时 < 30 秒
- 右侧出现 GIF tab，**自动播放**
- 不要求用户确认任何代码

**失败看**:
- 是否拆成多次 MCP 调用（slice + render×10 + runPython）
- GIF 是否每帧只显示一个平面（相机角度对）
- 合并 VTP tab 仍可用

---

### 3.2 复杂 Python 脚本（带确认流程）
**输入**: `用 matplotlib 画 wall 沿 x 方向的 Cp 分布`
**预期**:
1. LLM 询问："需要执行 Python 代码，是否允许？"
2. 用户回 "可以" / "确认"
3. LLM **立即** 执行 runPython（不要再问第二次）
4. 看到 spinner "正在准备 runPython..."（带旋转动画）
5. 输出 PNG 到 artifact

**失败看**:
- 是否反复要求确认 4+ 次
- 是否说 "正在执行..." 但没真的调工具（卡死）
- runPython 失败是否反复换库（imageio → magick → PIL）

---

## 4. 4 个演示爆点（新功能）

### 4.1 线数据曲线 ⭐
**输入**: `给我 ysy.cgns 的 wall 区域，从最低点到最高点的压力分布曲线`
**预期**:
- `calculate(method="probe_line", params={"scalar":"Pressure", "point1":[..], "point2":[..]})`
- 右侧 artifact 出现 PNG 曲线图（带 min/max 标注）
- 数据 CSV 也保存了

---

### 4.2 自动质量检查 ⭐
**输入**: `检查一下这个仿真有没有问题`
**预期**:
- `calculate(method="check")`
- 报告 errors/warnings 列表
- 如果有负压力/NaN/极端值，指出具体 zone 和数值

---

### 4.3 跨文件对比 ⭐
**前置**: 加载 ysy.cgns + j20_1.cgns
**输入**: `对比 ysy 和 j20_1 的 wall 压力`
**预期**:
- `diffZones(source_a="wall:Pressure", source_b="wall:Pressure", file_b="...j20_1.cgns")`
- 输出两文件的均值/最大/最小/差值

**失败看**: 是否报"Scalar mismatch" 或 "File not loaded"

---

### 4.4 自动报告 ⭐
**输入**: `给我出一份 x37b 的完整分析报告`
**预期**:
- LLM 自动串联 6 步（**不要每步问**）：
  1. 文件概要
  2. check 质量
  3. statistics 各 zone
  4. force_moment（如果有 wall）
  5. render 关键云图
  6. markdown 汇总
- 中间步骤不要等用户确认

---

## 5. 高级场景（考验 Agent 综合能力）

### 5.1 算法缺失 → Coding 兜底 ⭐⭐
**输入**: `算一下湍动能 TKE 的分布`（或 `计算雷诺应力`、`计算总焓`）
**预期**:
- LLM 检查 method 表 → 没有 TKE 算法
- LLM 检查 loadFile 标量列表 → 看是否有 TurbulentKineticEnergy 或类似
- **如果有现成标量** → 直接用 statistics + render
- **如果没有** → 主动说："没有 TKE 算法，需要用 runPython 从 k-omega 模型变量计算，是否允许？"
- 用户确认后 → runPython 计算 + 渲染

**失败看**:
- 是否直接说"无法计算"放弃
- 是否乱用 velocity_gradient 凑答案

---

### 5.2 多曲线对比图 ⭐⭐
**输入**: `对比 X=2、X=5、X=10 三个截面的压力沿 Y 方向分布`
**预期**:
- LLM 调用 3 次 `probe_line`（不同 point1/point2）
- 然后用 `runPython` 把 3 个 CSV 合到一张图（matplotlib，不同颜色 + 图例）
- 输出对比 PNG 到 artifact
- 回答里指出三条曲线的差异（哪个有激波、哪个最大值更高）

**失败看**:
- 是否只做了一条线就完事
- 对比图是否有图例区分三个截面

---

### 5.3 跨工况对比曲线（不同文件）⭐⭐
**前置**: 加载 AOA10.5_mach1.2.cgns + j20_1.cgns
**输入**: `对比这两个工况壁面 X 方向的压力分布`
**预期**:
- LLM 在两个文件分别调 `probe_line`
- 用 `runPython` 合成对比图（实线/虚线区分）
- 分析升力差异原因（"AOA10.5 上翼面吸力峰更强"等）

---

### 5.4 提取流线数据 ⭐
**输入**: `给我从点 (0,0,0) 出发的那条流线的坐标和速度数据，导出 CSV`
**预期**:
- LLM 调 `streamline` 生成 VTP
- 用 `runPython` 读 VTP，用 `vtk.vtkXMLPolyDataReader` 提取点坐标 + 标量
- 写出 CSV，列：x, y, z, VelocityX, VelocityY, VelocityZ, Mach...
- artifact 显示 CSV 表格

**失败看**:
- streamline 现在不支持指定单一种子点（只能 line/sphere），可能要改算法或用 runPython 直接做
- LLM 是否会想到这点

---

### 5.5 多结果汇总到 Excel ⭐⭐
**输入**: `把 ysy.cgns 所有 zone 的标量统计结果导出到一个 Excel 文件，每个 zone 一个 sheet`
**预期**:
- LLM 对每个 zone 调 `statistics`
- 用 `runPython` + `openpyxl` 或 `pandas.ExcelWriter` 写多 sheet xlsx
- 输出 .xlsx 到 artifact

**失败看**:
- 是否检查到 openpyxl 是否可用（动态库检测）
- 不可用时是否降级到多个 CSV

---

### 5.6 带物理分析的解读 ⭐⭐⭐
**输入**: `分析一下激波在哪里`
**预期**:
- LLM 推断需要看 Mach 数分布
- slice 沿来流方向几个截面，按 Mach 着色
- 渲染 PNG
- 回答："X=3.2 处 Mach 数从 1.5 跳到 0.8，对应正激波。下游 X=5 处出现弱反射激波。"
- 不只是给图，要给**结论**

**失败看**:
- 是否只画图不分析
- 数值定位是否合理（不是瞎说）

---

### 5.7 关键信息提取（结构化）⭐
**输入**: `这个文件最关键的几个数我看下：CL/CD/最大Mach/最低压力/Y+ 范围`
**预期**:
- LLM 串联多个 calculate
- 输出一张表格：
  ```
  | 指标 | 值 | 位置/zone |
  |------|----|-----------| 
  | CL   | ... | wall |
  | ...  | ... | ...  |
  ```
- 不要把每次 statistics 的整个 JSON 都贴出来

---

### 5.8 自由提问（开放性）
**输入**: 用工程师常问的真实问题，看 LLM 怎么处理：
- "翼尖有没有分离？"
- "哪里压力梯度最陡？"
- "尾流在 X 多远处衰减完？"
- "这个网格质量怎么样？"

**预期**: LLM 主动选合适的工具组合，给出**带数值依据**的判断，而不是套话。

---

## 6. UI/UX 体验（视觉检查）

### 6.1 左侧 Sidebar
```
□ 鼠标移上去自动展开
□ 点 pin 图标固定，固定后右侧内容向右让位
□ 取消 pin 后内容回到左边
```

### 6.2 工具卡片
```
□ tool_call 生成期间显示带 spinner 的 "正在准备 xxx..."
□ tool_start 后变成蓝色边框 + spinner + 工具名 + 参数 + 计时
□ tool 完成后变成绿色✓ + 耗时 + summary 一行
```

### 6.3 文字格式
```
□ LLM 输出长文本无大量空行（trim 生效）
□ Markdown 表格正常渲染
□ 文件路径变成可点击的蓝色链接（点击打开文件管理器）
```

### 6.4 Artifact tab
```
□ 同名 artifact 覆盖旧的，不累积
□ GIF/PNG 直接在 panel 里播放/显示
□ VTP 切片用 VTK.js 3D 渲染
□ CSV 出表格 + 图表两种视图
```

---

## 7. 常见问题快速诊断

| 现象 | 第一时间检查 |
|---|---|
| 对话不响应 | F12 Console 看 WebSocket 状态 |
| LLM 卡在"正在执行..." | Agent 窗口最后几行 `[Timing]` 日志 |
| loadFile 几十秒 | 看 Agent 窗口 `[Timing]` 拆解：LLM / MCP / engine |
| GIF 不显示 | F12 Network 看 `/api/file/xxx.gif` 是否 200 |
| Artifact 显示 JSON 而不是图 | 检查 artifact `type` 字段（应为 `image`）|
| LLM 反复确认 | 看 skills.py 第 11 条规则是否生效（需新对话）|
| 工具描述里说支持但实际没有 | 重启 PostService 让动态库检测重跑 |

---

## 8. 一键回归（最小测试集）

时间紧时只跑这 8 个：

```
1. 加载 ysy.cgns
2. 加载 x37b（验证模糊搜索）
3. 沿 X 切 10 个切片做 GIF
4. 检查质量
5. 给我压力分布曲线
6. 对比 X=2、X=5、X=10 三个截面的压力分布   ← 多曲线对比
7. 算一下 TKE 分布   ← 触发 coding 兜底
8. 出一份完整报告
```

8 个全过 = 主要功能 + 高级场景都没坏。

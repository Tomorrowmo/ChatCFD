# Streamline Seeding Strategy — 技术方案

## 问题

流线可视化的核心挑战不是积分算法，而是**种子点放在哪**。放错位置 = 直线穿过远场，看不到任何流动特征。

## 文献基础

基于 Sane et al. 2020 综述论文：

> **"A Survey of Seed Placement and Streamline Selection Techniques"**
> Sudhanshu Sane, Roxana Bujack, Christoph Garth, Hank Childs
> Computer Graphics Forum, Vol. 39, No. 3 (EuroVis 2020)
> PDF: https://cdux.cs.uoregon.edu/pubs/SaneCGF.pdf

该综述将自动播种技术分为三大类：

| 类别 | 核心思路 | ROI 聚焦 | 冗余消除 | 计算性能 |
|------|---------|---------|---------|---------|
| **Density-based** | 均匀间距分布流线 | 低 | 中 | 快 |
| **Feature-based** | 按流动特征（涡量/临界点）加权 | **高** | 中 | 中 |
| **Similarity-based** | 预计算大量流线，聚类去重 | 中 | **高** | 慢 |

### 关键论文

| 论文 | 年份 | 核心贡献 |
|------|------|---------|
| Turk & Banks, SIGGRAPH | 1996 | 低通滤波能量函数优化流线分布 |
| Jobard & Lefer | 1997 | 等间距贪心算法，单参数 dsep 控制疏密（VTK 2D 实现基于此） |
| Mebarki et al. | 2005 | Delaunay 三角化找最大空隙播种，比 Turk & Banks 快 200x |
| Verma et al., IEEE Vis | 2000 | 临界点检测 + 按类型模板播种（涡核/鞍点/源/汇） |
| Xu et al., IEEE TVCG | 2010 | 信息熵驱动：高方向变化区域优先播种 |
| Wu et al., IEEE TVCG | 2010 | 拓扑感知 + 等间距，最佳综合效果 |

## 我们的方案选择

**Feature-based + Derived Field（涡量加权播种）**

理由：
1. 我们已有速度场三分量，可直接用 `vtkGradientFilter` 计算涡量
2. 涡量大小 = 流动特征强度（涡量高 = 有涡/分离/剪切层）
3. 用涡量作为播种权重，流线自然集中在"有意思"的区域
4. 计算成本可控：VTK 标准 filter，不依赖自研模块

### 核心原理

**速度大小 ≠ 流动特征。涡量大小 = 流动特征。**

- 远场来流：速度高，涡量≈0 → 不需要流线
- 物体绕流：速度可能低，涡量高 → 需要流线
- 尾迹区：速度中等，涡量高 → 需要流线
- 分离点：速度≈0，涡量极高 → 最需要流线

涡量 ω = ∇ × V（速度场的旋度），只需要速度三分量即可计算：

```
ωx = ∂Vz/∂y - ∂Vy/∂z
ωy = ∂Vx/∂z - ∂Vz/∂x
ωz = ∂Vy/∂x - ∂Vx/∂y
|ω| = sqrt(ωx² + ωy² + ωz²)
```

## 实现方案

### 自动播种算法（seed_strategy="auto"）

```
输入：体网格 + 速度三分量
输出：种子点集合

1. 用 vtkGradientFilter 计算涡量场 |ω|
2. 检测物体（wall zone）位置
3. 分区域播种：
   a. 物体上游区域（30%种子）
      - 在物体前方 0.5~1.0 倍体长范围内
      - 均匀网格播种（保证来流覆盖）
   b. 物体附近高涡量区域（50%种子）
      - 在物体 ±2 倍体长范围内
      - 按 |ω| 加权采样（涡量越高越密集）
      - 排除物体内部的点
   c. 尾迹区域（20%种子）
      - 在物体下游 0.5~3.0 倍体长范围内
      - 按 |ω| 加权采样（捕捉尾涡）
4. 合并所有种子点，传给 vtkStreamTracer
```

### 参数自适应

| 参数 | 自动值 | 依据 |
|------|--------|------|
| 种子数量 | 80 | 经验值，兼顾覆盖和性能 |
| 涡量基线权重 | P30(|ω|) | 加到权重上，保证低涡量区也有少量种子 |
| 积分步长 | RK45 自适应 | diagonal × 0.001 初始步长 |
| 最大长度 | 2× 域对角线 | 保证流线不过早截断 |
| Tube 半径 | body_diag × 0.003 | 基于物体大小，非域大小 |

### 当前实现（已落地到 `post_service/algorithms/streamline.py`）

#### 涡量计算

```python
def _compute_vorticity(data_with_vel):
    """用 vtkGradientFilter 计算涡量（标准 VTK，不依赖自研模块）"""
    gradient = vtk.vtkGradientFilter()
    gradient.SetInputData(data_with_vel)
    gradient.SetInputArrayToProcess(
        0, 0, 0, vtk.vtkDataObject.FIELD_ASSOCIATION_POINTS, "Velocity_Vector"
    )
    gradient.ComputeVorticityOn()
    gradient.SetVorticityArrayName("Vorticity")
    gradient.Update()
    vort_arr = gradient.GetOutput().GetPointData().GetArray("Vorticity")
    return np.linalg.norm(vtk_to_numpy(vort_arr), axis=1)  # |ω|
```

#### 3-Zone 播种

```python
# Zone A: 物体上游 0.3~1.5 倍体长 — 速度加权均匀采样
zone_a = valid & (projections < body_proj - body_diag*0.3) & (projections > body_proj - body_diag*1.5)
weights_a = vel_mag[idx_a]  # 速度权重，保证来流覆盖

# Zone B: 物体附近 ±0.5 倍体长 — 涡量加权采样（核心）
zone_b = valid & (projections >= upstream_limit) & (projections < body_proj + body_diag*0.5)
weights_b = vort_mag[idx_b] + np.percentile(vort_mag[idx_b], 30)  # 涡量 + 基线

# Zone C: 尾迹区 0.3~3.0 倍体长下游 — 涡量加权采样
zone_c = valid & (projections >= body_proj + body_diag*0.3) & (projections < body_proj + body_diag*3.0)
weights_c = vort_mag[idx_c] + np.percentile(vort_mag[idx_c], 20)  # 涡量 + 基线
```

#### 物体检测

```python
def _find_body_bounds(multiblock):
    """从 multiblock 中找 wall/body zone 的包围盒"""
    # 1. 按名字匹配：wall, body, wing, surface, blade, airfoil, hull
    # 2. 找不到则取最小 zone（通常是物体表面）
```

#### 关键设计决策

- **种子必须是体网格中的真实点**：在网格外部生成的种子 vtkStreamTracer 无法插值，会产出空结果
- **涡量权重加基线**：`weights = vort_mag + P30(vort_mag)`，确保低涡量区域也有少量种子覆盖
- **排除物体内部**：body bbox 收缩 5% 范围内的点被排除，避免种子落在固体里
- **Tube 半径基于物体大小**：外流场域对角线远大于物体，用域对角线算半径会太粗

## 未来改进方向

1. **Q-criterion 替代涡量** — Q > 0 是更严格的涡核判据，避免剪切层误判
2. **等间距后处理** — 播种后用 Jobard & Lefer 的 dsep 检查，移除过近的流线
3. **信息熵驱动** — Xu et al. 2010 的条件熵方法，迭代添加信息增益最大的流线
4. **视角相关** — 根据当前 3D 视角优化流线可见性（适合交互场景）

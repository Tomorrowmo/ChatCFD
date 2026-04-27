# Four Demo Features Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add 4 features that showcase ChatCFD's AI analysis capabilities: line data plots, auto reports, cross-file comparison, simulation quality checks.

**Architecture:** Each feature is either a new algorithm plugin in `post_service/algorithms/` or a Skill prompt update in `agent/skills.py`. All follow existing patterns: NAME/DESCRIPTION/DEFAULTS/execute(). No new MCP tools needed — everything goes through existing `calculate()`.

**Tech Stack:** VTK (vtkProbeFilter for line data), numpy, matplotlib, existing PostData API.

**Test command:** `cd d:/Git/chatCFD && D:/TOOL/Conda/conda/envs/PostProcessTool/python.exe -m pytest tests/ -v`

---

### Task 1: Line Data Distribution (probe_line algorithm)

**What:** Sample scalars along a user-defined line → output CSV + matplotlib chart PNG.
**Use case:** "给我翼根到翼尖沿展向的 Cp 分布曲线"

**Files:**
- Create: `post_service/algorithms/probe_line.py`
- Modify: `agent/skills.py` (add to method table)

**Implementation:**

Create `post_service/algorithms/probe_line.py`:

```python
"""Sample scalar values along a line and generate distribution plot."""

import os
import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy

NAME = "probe_line"
DESCRIPTION = """沿一条直线采样标量值，生成分布曲线图（PNG）+ 数据（CSV）。
point1/point2: 线的起止坐标 [x,y,z]，不传则自动取 zone bbox 对角线。
scalar: 采样的标量名。resolution: 采样点数（默认 200）。
适用：Cp 沿弦长分布、压力沿展向变化、温度沿流向梯度。"""
DEFAULTS = {
    "scalar": None,         # required
    "point1": None,         # [x,y,z] start (None = auto)
    "point2": None,         # [x,y,z] end (None = auto)
    "resolution": 200,      # number of sample points
    "axis_label": None,     # x-axis label (None = auto: "Distance")
    "output_images": True,  # generate matplotlib chart
}


def execute(post_data, params: dict, zone_name: str, **kwargs) -> dict:
    scalar_name = params.get("scalar")
    if not scalar_name:
        return {"error": "Parameter 'scalar' is required."}

    zones = post_data.get_zones()
    ref_zone = zone_name if zone_name and zone_name in zones else zones[0]
    ref_block = post_data._get_block(ref_zone)

    try:
        resolved = post_data._resolve_name(ref_zone, scalar_name, ref_block)
    except ValueError as e:
        return {"error": str(e)}

    # Get target data
    multiblock = post_data.get_vtk_data()
    if zone_name:
        target = None
        for i in range(multiblock.GetNumberOfBlocks()):
            meta = multiblock.GetMetaData(i)
            if meta and meta.Get(vtk.vtkCompositeDataSet.NAME()) == zone_name:
                target = multiblock.GetBlock(i)
                break
        if target is None:
            return {"error": f"Zone '{zone_name}' not found"}
    else:
        append = vtk.vtkAppendFilter()
        for i in range(multiblock.GetNumberOfBlocks()):
            block = multiblock.GetBlock(i)
            if block:
                append.AddInputData(block)
        append.Update()
        target = append.GetOutput()

    # Cell to point if needed
    if target.GetPointData().GetArray(resolved) is None and \
       target.GetCellData().GetArray(resolved) is not None:
        c2p = vtk.vtkCellDataToPointData()
        c2p.SetInputData(target)
        c2p.Update()
        target = c2p.GetOutput()

    # Auto line endpoints from bounds
    bounds = target.GetBounds()
    p1 = params.get("point1") or [bounds[0], bounds[2], bounds[4]]
    p2 = params.get("point2") or [bounds[1], bounds[3], bounds[5]]
    resolution = int(params.get("resolution", 200))

    # Create probe line
    line = vtk.vtkLineSource()
    line.SetPoint1(*[float(v) for v in p1])
    line.SetPoint2(*[float(v) for v in p2])
    line.SetResolution(resolution)
    line.Update()

    probe = vtk.vtkProbeFilter()
    probe.SetInputConnection(line.GetOutputPort())
    probe.SetSourceData(target)
    probe.Update()
    probed = probe.GetOutput()

    # Extract data
    arr = probed.GetPointData().GetArray(resolved)
    if arr is None:
        return {"error": f"Probe returned no data for '{scalar_name}'. Check point1/point2 are inside the mesh."}

    values = vtk_to_numpy(arr)
    coords = vtk_to_numpy(probed.GetPoints().GetData())
    distances = np.sqrt(np.sum(np.diff(coords, axis=0, prepend=coords[:1])**2, axis=1))
    distances = np.cumsum(distances)

    # Filter out invalid probe points (value = 0 where probe missed the mesh)
    valid = probed.GetPointData().GetArray("vtkValidPointMask")
    if valid is not None:
        mask = vtk_to_numpy(valid).astype(bool)
        distances = distances[mask]
        values = values[mask]
        coords = coords[mask]

    if len(values) == 0:
        return {"error": "Probe line is entirely outside the mesh. Adjust point1/point2."}

    # Output paths
    file_stem = os.path.splitext(os.path.basename(post_data.file_path))[0]
    output_dir = os.path.join(os.path.dirname(post_data.file_path), file_stem)
    plot_dir = os.path.join(output_dir, "Plot")
    os.makedirs(plot_dir, exist_ok=True)

    zone_label = zone_name or "all"
    base_name = f"{zone_label}_{scalar_name}_line"

    # Save CSV
    csv_path = os.path.normpath(os.path.join(plot_dir, f"{base_name}.csv")).replace("\\", "/")
    import csv
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["distance", "x", "y", "z", scalar_name])
        for i in range(len(values)):
            w.writerow([float(distances[i]), float(coords[i][0]), float(coords[i][1]), float(coords[i][2]), float(values[i])])

    output_files = [csv_path]
    chart_path = None

    # Generate plot
    if params.get("output_images", True):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(distances, values, "b-", linewidth=1.5)
        ax.set_xlabel(params.get("axis_label") or "Distance")
        ax.set_ylabel(scalar_name)
        ax.set_title(f"{scalar_name} along line ({zone_label})")
        ax.grid(True, alpha=0.3)

        # Mark min/max
        i_min, i_max = np.argmin(values), np.argmax(values)
        ax.annotate(f"min={values[i_min]:.4g}", xy=(distances[i_min], values[i_min]),
                    fontsize=8, color="blue")
        ax.annotate(f"max={values[i_max]:.4g}", xy=(distances[i_max], values[i_max]),
                    fontsize=8, color="red")

        fig.tight_layout()
        chart_path = os.path.normpath(os.path.join(plot_dir, f"{base_name}.png")).replace("\\", "/")
        fig.savefig(chart_path, dpi=150)
        plt.close(fig)
        output_files.append(chart_path)

    return {
        "type": "file",
        "summary": (
            f"Probed {scalar_name} along line from {p1} to {p2}: "
            f"{len(values)} points, range [{float(np.min(values)):.4g}, {float(np.max(values)):.4g}]. "
            f"CSV: {csv_path}" + (f" Chart: {chart_path}" if chart_path else "")
        ),
        "data": {
            "csv_file": csv_path,
            "chart_file": chart_path,
            "scalar": scalar_name,
            "point1": list(p1),
            "point2": list(p2),
            "n_points": len(values),
            "value_range": [float(np.min(values)), float(np.max(values))],
        },
        "output_files": output_files,
    }
```

Then add to `agent/skills.py` TOOLS table:
```
| probe_line | 沿直线采样标量分布（Cp/压力曲线）+ 自动出图 | 任意 zone |
```

**Verify:** `D:/TOOL/Conda/conda/envs/PostProcessTool/python.exe -c "from post_service.algorithms.probe_line import execute; print('OK')"`

---

### Task 2: Simulation Quality Check (check algorithm)

**What:** Automated quality checks on loaded data — negative density/pressure, NaN, extreme values, mesh quality hints.
**Use case:** "检查一下这个仿真结果有没有问题"

**Files:**
- Create: `post_service/algorithms/check.py`
- Modify: `agent/skills.py` (add to method table)

**Implementation:**

Create `post_service/algorithms/check.py`:

```python
"""Automated simulation quality checks."""

import numpy as np

NAME = "check"
DESCRIPTION = """自动检查仿真数据质量。检测：负密度/负压力、NaN/Inf、极端值、标量异常。
无需参数，自动扫描所有 zone 和标量。
适用：快速诊断仿真结果是否可信。"""
DEFAULTS = {}

# Rules: (scalar_pattern, check_name, check_func, severity)
_CHECKS = [
    # Negative values that should be positive
    {
        "patterns": ["pressure", "density", "temperature"],
        "name": "negative_value",
        "check": lambda arr: float(np.min(arr)) < 0,
        "detail": lambda name, arr: f"{name}: min={float(np.min(arr)):.4g} (should be > 0)",
        "severity": "error",
    },
    # NaN or Inf
    {
        "patterns": None,  # all scalars
        "name": "nan_inf",
        "check": lambda arr: bool(np.any(~np.isfinite(arr))),
        "detail": lambda name, arr: f"{name}: {int(np.sum(~np.isfinite(arr)))} NaN/Inf values ({np.sum(~np.isfinite(arr))/len(arr)*100:.1f}%)",
        "severity": "error",
    },
    # Extreme values (> 10 std from mean)
    {
        "patterns": None,
        "name": "extreme_outlier",
        "check": lambda arr: bool(np.any(np.abs(arr - np.nanmean(arr)) > 10 * np.nanstd(arr))) if np.nanstd(arr) > 0 else False,
        "detail": lambda name, arr: (
            f"{name}: {int(np.sum(np.abs(arr - np.nanmean(arr)) > 10 * np.nanstd(arr)))} extreme outliers "
            f"(> 10σ from mean={float(np.nanmean(arr)):.4g})"
        ),
        "severity": "warning",
    },
    # Mach > 50 (likely unphysical for most CFD)
    {
        "patterns": ["mach"],
        "name": "high_mach",
        "check": lambda arr: float(np.max(arr)) > 50,
        "detail": lambda name, arr: f"{name}: max={float(np.max(arr)):.4g} (> 50, likely unphysical)",
        "severity": "warning",
    },
]


def _match_pattern(scalar_name, patterns):
    if patterns is None:
        return True
    return any(p in scalar_name.lower() for p in patterns)


def execute(post_data, params: dict, zone_name: str, **kwargs) -> dict:
    zones = post_data.get_zones()
    if zone_name:
        zones = [zone_name] if zone_name in zones else []
    if not zones:
        return {"error": "No zones to check."}

    findings = []  # {zone, scalar, check, detail, severity}

    for zone in zones:
        scalars = post_data.get_scalar_names(zone)
        for scalar in scalars:
            try:
                arr = post_data.get_scalar(zone, scalar)
            except ValueError:
                continue
            if len(arr) == 0:
                continue

            for rule in _CHECKS:
                if not _match_pattern(scalar, rule["patterns"]):
                    continue
                try:
                    if rule["check"](arr):
                        findings.append({
                            "zone": zone,
                            "scalar": scalar,
                            "check": rule["name"],
                            "detail": rule["detail"](scalar, arr),
                            "severity": rule["severity"],
                        })
                except Exception:
                    pass

    errors = [f for f in findings if f["severity"] == "error"]
    warnings = [f for f in findings if f["severity"] == "warning"]

    if not findings:
        summary = f"All checks passed for {len(zones)} zone(s). No issues found."
    else:
        parts = []
        if errors:
            parts.append(f"{len(errors)} error(s)")
        if warnings:
            parts.append(f"{len(warnings)} warning(s)")
        detail_lines = [f"[{f['severity'].upper()}] {f['zone']}: {f['detail']}" for f in findings[:10]]
        summary = f"Found {', '.join(parts)} in {len(zones)} zone(s):\n" + "\n".join(detail_lines)

    return {
        "type": "numerical",
        "summary": summary,
        "data": {
            "zones_checked": len(zones),
            "errors": errors,
            "warnings": warnings,
            "total_issues": len(findings),
        },
        "output_files": [],
    }
```

Add to `agent/skills.py` TOOLS table:
```
| check | 自动检查仿真数据质量（负值/NaN/极端值） | 任意 zone |
```

---

### Task 3: Cross-File Comparison

**What:** Compare the same scalar between two different loaded files.
**Use case:** "对比 AOA5 和 AOA10 的壁面压力"

**Files:**
- Modify: `post_service/mcp_tools/compare.py` (add file_b parameter)
- Modify: `post_service/engine.py:234-257` (extend compare to cross-file)
- Modify: `agent/skills.py` (update compare description)

**Implementation:**

Replace `post_service/mcp_tools/compare.py`:

```python
"""MCP tool: compare — Compare scalars between zones or files."""


def register(mcp, engine):
    @mcp.tool()
    def compare(source_a: str, source_b: str, session_id: str = "default",
                file_b: str = "") -> dict:
        """Compare a scalar between two zones or two files.

        Same-file comparison:
            source_a = "zone_a:scalar", source_b = "zone_b:scalar"
        Cross-file comparison:
            source_a = "zone_a:scalar", source_b = "zone_b:scalar",
            file_b = "path/to/second/file.cgns"
            (file_b must be already loaded via loadFile)
        """
        return engine.compare(session_id, source_a, source_b, file_b=file_b)
```

Extend `post_service/engine.py` `compare()` method:

```python
def compare(self, session_id: str, source_a: str, source_b: str, **kwargs) -> dict:
    state = self.session_mgr.get(session_id)
    if state is None or state.post_data is None:
        return {"error": "No file loaded."}

    if ":" not in source_a or ":" not in source_b:
        return {"error": "source_a and source_b must use 'zone:scalar' format."}

    zone_a, scalar_a = source_a.split(":", 1)
    zone_b, scalar_b = source_b.split(":", 1)

    if scalar_a != scalar_b:
        return {"error": f"Scalar mismatch: '{scalar_a}' vs '{scalar_b}'."}

    # Cross-file: get post_data for file_b
    file_b = kwargs.get("file_b", "")
    if file_b:
        pd_b = state.get_post_data(file_b)
        if pd_b is None:
            return {"error": f"File '{file_b}' not loaded. Call loadFile first."}
    else:
        pd_b = None  # same file

    entry = self.registry.get("compare")
    if entry is None:
        return {"error": "Compare algorithm not loaded."}

    params = {
        **entry["defaults"],
        "scalar": scalar_a,
        "zone_a": zone_a,
        "zone_b": zone_b,
    }
    try:
        if pd_b:
            return entry["execute"](state.post_data, params, "", post_data_b=pd_b)
        return entry["execute"](state.post_data, params, "")
    except Exception as e:
        return {"error": f"Compare failed: {e}"}
```

Extend `post_service/algorithms/compare.py` to accept `post_data_b`:

```python
def execute(post_data, params: dict, zone_name: str, **kwargs) -> dict:
    scalar = params.get("scalar")
    zone_a = params.get("zone_a")
    zone_b = params.get("zone_b")
    post_data_b = kwargs.get("post_data_b")  # None = same file

    if not scalar:
        return {"error": "Parameter 'scalar' is required."}
    if not zone_a or not zone_b:
        return {"error": "Parameters 'zone_a' and 'zone_b' are required."}

    try:
        arr_a = post_data.get_scalar(zone_a, scalar)
    except ValueError as e:
        return {"error": f"File A: {e}"}
    try:
        source_b = post_data_b if post_data_b else post_data
        arr_b = source_b.get_scalar(zone_b, scalar)
    except ValueError as e:
        return {"error": f"File B: {e}"}

    # ... rest unchanged (stats + diff calculation) ...
```

Update `agent/skills.py`:
```
| compare | 两区域/两文件标量对比（需先 loadFile 两个文件） | — |
```

---

### Task 4: Auto Report (Skill prompt)

**What:** Skill-level prompt template that guides LLM to chain existing tools into a structured report.
**Use case:** "给我出一份完整的分析报告"

**Files:**
- Modify: `agent/skills.py` (add report workflow section)

**Implementation:**

Add to RULES in `agent/skills.py`, after the Coding workflow section:

```python
### 自动报告工作流
用户说"分析报告"/"完整报告"/"总结" → 按以下步骤串联：
1. **文件概要**：zone 列表 + 网格类型 + 点数/单元数
2. **标量统计**：每个 zone 调 calculate(method="statistics")
3. **气动力**：壁面 zone 调 calculate(method="force_moment")（如果有参考参数）
4. **质量检查**：调 calculate(method="check") 扫描异常
5. **关键云图**：壁面压力渲染 calculate(method="render", scalar="Pressure")
6. **汇总结论**：用 2-3 句话总结关键发现（升阻比、异常、建议）

每步完成后直接进入下一步，不要问用户。最终输出结构化摘要。
```

---

### Task 5: Update Skills TOOLS table (all features)

**Files:**
- Modify: `agent/skills.py`

Add all new methods to the calculate method table:

```
| probe_line | 沿直线采样标量分布（Cp/压力曲线）+ 自动出图 | 任意 zone |
| check | 自动检查仿真数据质量（负值/NaN/极端值） | 任意 zone |
```

Update compare description:
```
| compare | 两区域/两文件标量对比（需先 loadFile 两个文件） | — |
```

---

### Task 6: Run all tests

Run: `D:/TOOL/Conda/conda/envs/PostProcessTool/python.exe -m pytest tests/ -v`

Expected: All pass, no regressions.

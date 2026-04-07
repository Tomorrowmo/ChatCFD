# Phase 1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement ChatCFD Phase 1 — 后处理服务（PostEngine + 6 MCP Tools + HTTP API）+ Agent 服务层，实现完整的对话→计算→返回链路。

**Architecture:** 后处理服务是一个 HTTP 服务，内含 MCP 端点（薄壳，给 LLM）和 HTTP API 端点（薄壳，给前端），核心逻辑在 PostEngine。Agent 服务层通过 MCP SSE 连接后处理服务，通过 LiteLLM 调用多种 LLM。前端暂不实现（Phase 1 用命令行或 Postman 验证）。

**Tech Stack:** Python 3.10+, FastAPI, FastMCP, LiteLLM, mcp SDK, VTK 9.4.1 (+ 自研 C++), numpy

**Implementation Order:**
```
Task 1-3: post_service 基础层（PostData + Session + Algorithm Registry）
Task 4-6: 算法插件（statistics + force_moment + velocity_gradient）
Task 7:   PostEngine 计算引擎
Task 8:   MCP 端点层（6 个 tool 薄壳）
Task 9:   HTTP API 端点层
Task 10:  后处理服务入口 server.py
Task 11:  Agent MCP Client
Task 12:  Agent Harness
Task 13:  Agent Session + Skills + Insight Log
Task 14:  Agent Loop
Task 15:  Agent 服务入口 main.py
Task 16:  集成测试
```

---

## Task 1: PostData 薄封装层

**Files:**
- Create: `post_service/post_data.py`
- Create: `post_service/config/physical_mapping.json`
- Test: `tests/post_service/test_post_data.py`

**Step 1: Create physical mapping config**

```json
// post_service/config/physical_mapping.json
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
  "velocity_y": {
    "standard_name": "velocity_y",
    "display_name": "Y方向速度",
    "unit": "m/s",
    "aliases": ["VelocityY", "Y_Velocity", "Uy", "U:1", "y-velocity"]
  },
  "velocity_z": {
    "standard_name": "velocity_z",
    "display_name": "Z方向速度",
    "unit": "m/s",
    "aliases": ["VelocityZ", "Z_Velocity", "Uz", "U:2", "z-velocity"]
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

**Step 2: Write failing tests for PostData**

```python
# tests/post_service/test_post_data.py
import pytest
import numpy as np
import vtk
from post_service.post_data import PostData


def make_test_multiblock():
    """Create a minimal vtkMultiBlockDataSet for testing."""
    mb = vtk.vtkMultiBlockDataSet()

    # Block 0: "wall" with Pressure and VelocityX
    grid = vtk.vtkUnstructuredGrid()
    points = vtk.vtkPoints()
    points.InsertNextPoint(0, 0, 0)
    points.InsertNextPoint(1, 0, 0)
    points.InsertNextPoint(0, 1, 0)
    grid.SetPoints(points)

    pressure = vtk.vtkFloatArray()
    pressure.SetName("Static_Pressure")
    pressure.InsertNextValue(101325.0)
    pressure.InsertNextValue(101300.0)
    pressure.InsertNextValue(101350.0)
    grid.GetPointData().AddArray(pressure)

    vel_x = vtk.vtkFloatArray()
    vel_x.SetName("X_Velocity")
    vel_x.InsertNextValue(100.0)
    vel_x.InsertNextValue(110.0)
    vel_x.InsertNextValue(105.0)
    grid.GetPointData().AddArray(vel_x)

    mb.SetBlock(0, grid)
    mb.GetMetaData(0).Set(vtk.vtkCompositeDataSet.NAME(), "wall")

    # Block 1: "far" with Pressure only
    grid2 = vtk.vtkUnstructuredGrid()
    points2 = vtk.vtkPoints()
    points2.InsertNextPoint(10, 0, 0)
    points2.InsertNextPoint(11, 0, 0)
    grid2.SetPoints(points2)

    pressure2 = vtk.vtkFloatArray()
    pressure2.SetName("Static_Pressure")
    pressure2.InsertNextValue(101325.0)
    pressure2.InsertNextValue(101325.0)
    grid2.GetPointData().AddArray(pressure2)

    mb.SetBlock(1, grid2)
    mb.GetMetaData(1).Set(vtk.vtkCompositeDataSet.NAME(), "far")

    return mb


class TestPostData:
    def setup_method(self):
        self.mb = make_test_multiblock()
        self.pd = PostData(self.mb, "test.cgns")

    def test_get_zones(self):
        zones = self.pd.get_zones()
        assert zones == ["wall", "far"]

    def test_get_scalar_by_raw_name(self):
        arr = self.pd.get_scalar("wall", "Static_Pressure")
        assert isinstance(arr, np.ndarray)
        assert len(arr) == 3
        assert not arr.flags.writeable  # must be read-only

    def test_get_scalar_by_standard_name(self):
        """physical mapping: 'pressure' -> 'Static_Pressure'"""
        arr = self.pd.get_scalar("wall", "pressure")
        assert isinstance(arr, np.ndarray)
        assert len(arr) == 3

    def test_get_scalar_not_found(self):
        with pytest.raises(ValueError, match="not found"):
            self.pd.get_scalar("wall", "nonexistent_field")

    def test_get_points(self):
        pts = self.pd.get_points("wall")
        assert pts.shape == (3, 3)
        assert not pts.flags.writeable

    def test_get_scalar_names(self):
        names = self.pd.get_scalar_names("wall")
        assert "Static_Pressure" in names
        assert "X_Velocity" in names

    def test_get_bounds(self):
        bounds = self.pd.get_bounds("wall")
        assert "xmin" in bounds and "xmax" in bounds

    def test_get_summary(self):
        summary = self.pd.get_summary()
        assert "zones" in summary
        assert len(summary["zones"]) == 2

    def test_get_vtk_data(self):
        vtk_data = self.pd.get_vtk_data()
        assert vtk_data is self.mb

    def test_invalid_zone(self):
        with pytest.raises(ValueError, match="not found"):
            self.pd.get_scalar("nonexistent_zone", "pressure")
```

**Step 3: Run tests to verify they fail**

Run: `cd d:\Git\chatCFD && python -m pytest tests/post_service/test_post_data.py -v`
Expected: FAIL (ModuleNotFoundError: post_service.post_data)

**Step 4: Implement PostData**

```python
# post_service/post_data.py
import json
import os
import numpy as np
from vtk.util.numpy_support import vtk_to_numpy
import vtk


def _load_physical_mapping():
    mapping_path = os.path.join(os.path.dirname(__file__), "config", "physical_mapping.json")
    if os.path.exists(mapping_path):
        with open(mapping_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


class PostData:
    """VTK 数据的薄封装访问层。不复制数据，通过 vtk_to_numpy 零拷贝引用 VTK 内存。"""

    def __init__(self, multiblock, file_path: str):
        self._multiblock = multiblock
        self.file_path = file_path
        self._mapping = _load_physical_mapping()
        self._resolved = {}  # cache: {(zone, standard_name): actual_name}
        self._zone_index = self._build_zone_index()

    def _build_zone_index(self) -> dict:
        """Build {zone_name: block_index} mapping."""
        index = {}
        for i in range(self._multiblock.GetNumberOfBlocks()):
            block = self._multiblock.GetBlock(i)
            if block is None:
                continue
            meta = self._multiblock.GetMetaData(i)
            if meta:
                name = meta.Get(vtk.vtkCompositeDataSet.NAME())
                if name:
                    index[name] = i
        return index

    def _get_block(self, zone: str):
        if zone not in self._zone_index:
            available = list(self._zone_index.keys())
            raise ValueError(f"Zone '{zone}' not found. Available: {available}")
        return self._multiblock.GetBlock(self._zone_index[zone])

    def get_zones(self) -> list:
        return list(self._zone_index.keys())

    def get_scalar(self, zone: str, name: str) -> np.ndarray:
        block = self._get_block(zone)
        actual_name = self._resolve_name(zone, name, block)
        vtk_array = block.GetPointData().GetArray(actual_name)
        if vtk_array is None:
            vtk_array = block.GetCellData().GetArray(actual_name)
        if vtk_array is None:
            raise ValueError(f"Scalar '{name}' not found in zone '{zone}'")
        arr = vtk_to_numpy(vtk_array)
        arr.flags.writeable = False
        return arr

    def get_points(self, zone: str) -> np.ndarray:
        block = self._get_block(zone)
        vtk_points = block.GetPoints()
        if vtk_points is None:
            raise ValueError(f"Zone '{zone}' has no points")
        arr = vtk_to_numpy(vtk_points.GetData())
        arr.flags.writeable = False
        return arr

    def get_scalar_names(self, zone: str) -> list:
        block = self._get_block(zone)
        names = []
        pd = block.GetPointData()
        for i in range(pd.GetNumberOfArrays()):
            names.append(pd.GetArray(i).GetName())
        cd = block.GetCellData()
        for i in range(cd.GetNumberOfArrays()):
            names.append(cd.GetArray(i).GetName())
        return names

    def get_bounds(self, zone: str) -> dict:
        block = self._get_block(zone)
        b = block.GetBounds()
        return {"xmin": b[0], "xmax": b[1], "ymin": b[2], "ymax": b[3], "zmin": b[4], "zmax": b[5]}

    def get_summary(self) -> dict:
        zones = []
        for zone_name in self._zone_index:
            block = self._get_block(zone_name)
            scalars = []
            pd = block.GetPointData()
            for i in range(pd.GetNumberOfArrays()):
                raw_name = pd.GetArray(i).GetName()
                mapped = self._find_standard_name(raw_name)
                scalars.append({
                    "raw_name": raw_name,
                    "mapped_to": mapped,
                    "display": self._mapping[mapped]["display_name"] + f"({self._mapping[mapped]['unit']})" if mapped else raw_name,
                })
            zones.append({
                "name": zone_name,
                "n_cells": block.GetNumberOfCells(),
                "n_points": block.GetNumberOfPoints(),
                "scalars": scalars,
            })
        return {
            "file_path": self.file_path,
            "zones": zones,
            "n_zones": len(zones),
        }

    def get_vtk_data(self):
        return self._multiblock

    def _resolve_name(self, zone: str, name: str, block) -> str:
        cache_key = (zone, name)
        if cache_key in self._resolved:
            return self._resolved[cache_key]
        # 1. Direct match
        if self._has_scalar(block, name):
            self._resolved[cache_key] = name
            return name
        # 2. Mapping table lookup
        if name in self._mapping:
            for alias in self._mapping[name]["aliases"]:
                if self._has_scalar(block, alias):
                    self._resolved[cache_key] = alias
                    return alias
        # 3. Not found
        available = self.get_scalar_names(zone)
        raise ValueError(f"Scalar '{name}' not found in zone '{zone}'. Available: {available}")

    def _has_scalar(self, block, name: str) -> bool:
        return (block.GetPointData().GetArray(name) is not None or
                block.GetCellData().GetArray(name) is not None)

    def _find_standard_name(self, raw_name: str):
        """Reverse lookup: raw_name -> standard_name or None."""
        for std_name, info in self._mapping.items():
            if raw_name in info["aliases"] or raw_name == std_name:
                return std_name
        return None
```

**Step 5: Run tests to verify they pass**

Run: `cd d:\Git\chatCFD && python -m pytest tests/post_service/test_post_data.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add post_service/post_data.py post_service/config/physical_mapping.json tests/post_service/test_post_data.py post_service/__init__.py
git commit -m "feat(post_service): add PostData thin wrapper with physical mapping"
```

---

## Task 2: Session Manager

**Files:**
- Create: `post_service/session.py`
- Test: `tests/post_service/test_session.py`

**Step 1: Write failing tests**

```python
# tests/post_service/test_session.py
import pytest
from post_service.session import SessionState, SessionManager


class TestSessionManager:
    def setup_method(self):
        self.mgr = SessionManager()

    def test_create_session(self):
        state = self.mgr.create("sess1")
        assert state is not None
        assert state.post_data is None
        assert state.output_dir is None

    def test_get_session(self):
        self.mgr.create("sess1")
        state = self.mgr.get("sess1")
        assert state is not None

    def test_get_nonexistent(self):
        assert self.mgr.get("nonexistent") is None

    def test_destroy_session(self):
        self.mgr.create("sess1")
        self.mgr.destroy("sess1")
        assert self.mgr.get("sess1") is None

    def test_multiple_sessions(self):
        self.mgr.create("a")
        self.mgr.create("b")
        assert self.mgr.get("a") is not None
        assert self.mgr.get("b") is not None
        assert self.mgr.get("a") is not self.mgr.get("b")
```

**Step 2: Run tests, verify fail**

**Step 3: Implement**

```python
# post_service/session.py
import time


class SessionState:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.post_data = None       # PostData instance, set after loadFile
        self.output_dir = None      # auto-set to file's directory
        self.created_at = time.time()
        self.last_active = time.time()

    def touch(self):
        self.last_active = time.time()


class SessionManager:
    def __init__(self, timeout_seconds: int = 3600):
        self._sessions = {}
        self._timeout = timeout_seconds

    def create(self, session_id: str) -> SessionState:
        state = SessionState(session_id)
        self._sessions[session_id] = state
        return state

    def get(self, session_id: str):
        state = self._sessions.get(session_id)
        if state:
            state.touch()
        return state

    def destroy(self, session_id: str):
        state = self._sessions.pop(session_id, None)
        if state and state.post_data:
            state.post_data = None  # release VTK reference

    def cleanup_expired(self):
        now = time.time()
        expired = [sid for sid, s in self._sessions.items()
                   if now - s.last_active > self._timeout]
        for sid in expired:
            self.destroy(sid)
```

**Step 4: Run tests, verify pass**

**Step 5: Commit**

```bash
git add post_service/session.py tests/post_service/test_session.py
git commit -m "feat(post_service): add SessionState and SessionManager"
```

---

## Task 3: Algorithm Registry

**Files:**
- Create: `post_service/algorithm_registry.py`
- Create: `post_service/algorithms/__init__.py`
- Test: `tests/post_service/test_algorithm_registry.py`

**Step 1: Write failing tests**

```python
# tests/post_service/test_algorithm_registry.py
import pytest
from post_service.algorithm_registry import AlgorithmRegistry


class TestAlgorithmRegistry:
    def test_scan_loads_algorithms(self, tmp_path):
        # Create a dummy algorithm file
        algo_file = tmp_path / "dummy_algo.py"
        algo_file.write_text('''
NAME = "dummy"
DESCRIPTION = "A dummy algorithm"
DEFAULTS = {"param1": 1.0, "param2": None}

def execute(post_data, params, zone_name):
    return {"type": "numerical", "summary": "ok", "data": {}, "output_files": []}
''')
        registry = AlgorithmRegistry()
        registry.scan_and_load(str(tmp_path))
        assert "dummy" in registry.methods
        entry = registry.methods["dummy"]
        assert entry["description"] == "A dummy algorithm"
        assert entry["defaults"]["param1"] == 1.0
        assert callable(entry["execute"])

    def test_get_method(self, tmp_path):
        algo_file = tmp_path / "test_algo.py"
        algo_file.write_text('''
NAME = "test"
DESCRIPTION = "Test"
DEFAULTS = {}
def execute(post_data, params, zone_name):
    return {"type": "numerical", "summary": "ok", "data": {}, "output_files": []}
''')
        registry = AlgorithmRegistry()
        registry.scan_and_load(str(tmp_path))
        assert registry.get("test") is not None
        assert registry.get("nonexistent") is None

    def test_list_methods(self, tmp_path):
        algo_file = tmp_path / "algo.py"
        algo_file.write_text('NAME="a"\nDESCRIPTION="desc"\nDEFAULTS={}\ndef execute(p,q,z): pass')
        registry = AlgorithmRegistry()
        registry.scan_and_load(str(tmp_path))
        methods = registry.list_methods()
        assert len(methods) == 1
        assert methods[0]["name"] == "a"
```

**Step 2: Run tests, verify fail**

**Step 3: Implement**

```python
# post_service/algorithm_registry.py
import importlib.util
import os


class AlgorithmRegistry:
    def __init__(self):
        self.methods = {}

    def scan_and_load(self, algorithms_dir: str):
        if not os.path.isdir(algorithms_dir):
            return
        for filename in sorted(os.listdir(algorithms_dir)):
            if not filename.endswith(".py") or filename.startswith("_"):
                continue
            filepath = os.path.join(algorithms_dir, filename)
            spec = importlib.util.spec_from_file_location(filename[:-3], filepath)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            name = getattr(module, "NAME", None)
            if name is None:
                continue
            self.methods[name] = {
                "name": name,
                "description": getattr(module, "DESCRIPTION", ""),
                "defaults": getattr(module, "DEFAULTS", {}),
                "execute": module.execute,
            }

    def get(self, method_name: str):
        return self.methods.get(method_name)

    def list_methods(self) -> list:
        return [{"name": m["name"], "description": m["description"],
                 "defaults": m["defaults"]} for m in self.methods.values()]
```

**Step 4: Run tests, verify pass**

**Step 5: Commit**

```bash
git add post_service/algorithm_registry.py post_service/algorithms/__init__.py tests/post_service/test_algorithm_registry.py
git commit -m "feat(post_service): add AlgorithmRegistry with auto-scan"
```

---

## Task 4: statistics 算法插件

**Files:**
- Create: `post_service/algorithms/statistics.py`
- Test: `tests/post_service/algorithms/test_statistics.py`

**Step 1: Write failing tests**

```python
# tests/post_service/algorithms/test_statistics.py
import pytest
import numpy as np
from unittest.mock import MagicMock
from post_service.algorithms.statistics import execute, NAME, DEFAULTS


def make_mock_post_data():
    pd = MagicMock()
    pd.get_scalar.return_value = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    pd.get_scalar_names.return_value = ["Pressure", "Temperature"]
    pd.get_zones.return_value = ["wall"]
    return pd


class TestStatistics:
    def test_name(self):
        assert NAME == "statistics"

    def test_single_scalar(self):
        pd = make_mock_post_data()
        result = execute(pd, {"scalars": ["Pressure"]}, "wall")
        assert result["type"] == "numerical"
        assert "summary" in result
        assert "data" in result
        stats = result["data"]["Pressure"]
        assert stats["min"] == 1.0
        assert stats["max"] == 5.0
        assert stats["mean"] == 3.0

    def test_all_scalars(self):
        pd = make_mock_post_data()
        result = execute(pd, {}, "wall")  # no scalars specified = all
        assert len(result["data"]) == 2  # Pressure + Temperature
```

**Step 2: Run tests, verify fail**

**Step 3: Implement**

```python
# post_service/algorithms/statistics.py
import numpy as np

NAME = "statistics"
DESCRIPTION = "Calculate scalar statistics (min/max/mean/std) for a zone."
DEFAULTS = {
    "scalars": None,  # None = all scalars in zone
}


def execute(post_data, params: dict, zone_name: str) -> dict:
    scalars = params.get("scalars")
    if not scalars:
        scalars = post_data.get_scalar_names(zone_name)

    data = {}
    summaries = []
    for name in scalars:
        try:
            arr = post_data.get_scalar(zone_name, name)
        except ValueError:
            continue
        stats = {
            "min": float(np.min(arr)),
            "max": float(np.max(arr)),
            "mean": float(np.mean(arr)),
            "std": float(np.std(arr)),
        }
        data[name] = stats
        summaries.append(f"{name}: min={stats['min']:.4g}, max={stats['max']:.4g}, mean={stats['mean']:.4g}")

    return {
        "type": "numerical",
        "summary": f"{zone_name} statistics: " + "; ".join(summaries),
        "data": data,
        "output_files": [],
    }
```

**Step 4: Run tests, verify pass**

**Step 5: Commit**

```bash
git add post_service/algorithms/statistics.py tests/post_service/algorithms/test_statistics.py
git commit -m "feat(algorithms): add statistics plugin (numpy, no VTK)"
```

---

## Task 5: force_moment 算法插件

**Files:**
- Create: `post_service/algorithms/force_moment.py`
- Test: `tests/post_service/algorithms/test_force_moment.py`

**Step 1: Write failing test (smoke test with mock)**

```python
# tests/post_service/algorithms/test_force_moment.py
import pytest
from post_service.algorithms.force_moment import NAME, DEFAULTS, execute


class TestForceMomentMeta:
    def test_name(self):
        assert NAME == "force_moment"

    def test_defaults_has_required_params(self):
        assert "pressure" in DEFAULTS
        assert "density" in DEFAULTS
        assert "refArea" in DEFAULTS
        # density/refArea are None = required, AI must ask user
        assert DEFAULTS["density"] is None

    def test_defaults_structure(self):
        """DEFAULTS must be a dict, not a class."""
        assert isinstance(DEFAULTS, dict)
```

注意：force_moment 依赖 VTK C++ 模块 `ForceMomentIntegtal`，完整集成测试需要实际 VTK 数据。单元测试只验证插件结构和参数。

**Step 2: Run tests, verify fail**

**Step 3: Implement (from legacy/PostDrive/PostIntegral.py + ForceMomentIntegralStruct.py)**

```python
# post_service/algorithms/force_moment.py
import vtk

NAME = "force_moment"
DESCRIPTION = "Calculate force and moment integral (CL, CD, etc.)."
DEFAULTS = {
    "pressure": "pressure",
    "density": None,           # required, AI must ask
    "velocity": None,          # required, AI must ask
    "refArea": None,           # required for coefficients
    "refLength": 1.0,
    "flip_normals": True,
    "alpha_angle": 0.0,
    "beta_angle": 0.0,
    "reference_point": [0.0, 0.0, 0.0],
    "shear_force": None,       # optional: [fx_name, fy_name, fz_name]
}


def execute(post_data, params: dict, zone_name: str) -> dict:
    multiblock = post_data.get_vtk_data()

    # Collect target blocks
    if zone_name:
        block = _get_zone_block(multiblock, zone_name)
        if block is None:
            return {"error": f"Zone '{zone_name}' not found"}
        input_data = block
    else:
        input_data = _merge_all_blocks(multiblock)

    # Setup VTK filter
    fm = vtk.ForceMomentIntegtal()
    fm.SetInputData(input_data)
    fm.SetPressureName(str(params["pressure"]))
    fm.SetFlipNormals(bool(params["flip_normals"]))
    fm.SetAngles(float(params["alpha_angle"]), float(params["beta_angle"]))

    ref_pt = params["reference_point"]
    fm.SetReferencePoint(float(ref_pt[0]), float(ref_pt[1]), float(ref_pt[2]))

    density = params.get("density")
    velocity = params.get("velocity")
    ref_area = params.get("refArea")
    ref_length = params.get("refLength", 1.0)

    has_ref = all(v is not None for v in [density, velocity, ref_area])
    if has_ref:
        fm.SetReferenceCondition(float(density), float(velocity),
                                 float(ref_area), float(ref_length))

    shear = params.get("shear_force")
    if shear and len(shear) == 3:
        fm.SetShearForce(str(shear[0]), str(shear[1]), str(shear[2]))

    fm.Updata()  # note: legacy API typo preserved

    # Collect results
    force = {"x": fm.GetTotalForceX(), "y": fm.GetTotalForceY(), "z": fm.GetTotalForceZ()}
    moment = {"x": fm.GetTotalMomentX(), "y": fm.GetTotalMomentY(), "z": fm.GetTotalMomentZ()}

    result_data = {"force": force, "moment": moment}
    summary_parts = [f"Fx={force['x']:.2f}N, Fy={force['y']:.2f}N, Fz={force['z']:.2f}N"]

    if has_ref:
        coefficients = {
            "CL": fm.GetLiftCoefficient(),
            "CD": fm.GetDragCoefficient(),
            "CSF": fm.GetSideForceCoefficient(),
            "CMx": fm.GetRollingMomentCoefficient(),
            "CMy": fm.GetPitchingMomentCoefficient(),
            "CMz": fm.GetYawingMomentCoefficient(),
        }
        result_data["coefficients"] = coefficients
        summary_parts.append(f"CL={coefficients['CL']:.4f}, CD={coefficients['CD']:.4f}")

    zone_label = zone_name or "all zones"
    return {
        "type": "numerical",
        "summary": f"{zone_label}: " + "; ".join(summary_parts),
        "data": result_data,
        "output_files": [],
    }


def _get_zone_block(multiblock, zone_name):
    for i in range(multiblock.GetNumberOfBlocks()):
        meta = multiblock.GetMetaData(i)
        if meta and meta.Get(vtk.vtkCompositeDataSet.NAME()) == zone_name:
            return multiblock.GetBlock(i)
    return None


def _merge_all_blocks(multiblock):
    append = vtk.vtkAppendFilter()
    for i in range(multiblock.GetNumberOfBlocks()):
        block = multiblock.GetBlock(i)
        if block:
            append.AddInputData(block)
    append.Update()
    return append.GetOutput()
```

**Step 4: Run tests, verify pass**

**Step 5: Commit**

```bash
git add post_service/algorithms/force_moment.py tests/post_service/algorithms/test_force_moment.py
git commit -m "feat(algorithms): add force_moment plugin (VTK C++ wrapper)"
```

---

## Task 6: velocity_gradient 算法插件

**Files:**
- Create: `post_service/algorithms/velocity_gradient.py`
- Test: `tests/post_service/algorithms/test_velocity_gradient.py`

**Step 1: Write failing test (meta only)**

```python
# tests/post_service/algorithms/test_velocity_gradient.py
from post_service.algorithms.velocity_gradient import NAME, DEFAULTS


class TestVelocityGradientMeta:
    def test_name(self):
        assert NAME == "velocity_gradient"

    def test_defaults_structure(self):
        assert isinstance(DEFAULTS, dict)
        assert "velocity_x" in DEFAULTS
        assert "mach_switch" in DEFAULTS
```

**Step 2: Run tests, verify fail**

**Step 3: Implement (from legacy/PostDrive/PostVelocityGradient.py + VelocityGradientStruct.py)**

```python
# post_service/algorithms/velocity_gradient.py
import os
import vtk

NAME = "velocity_gradient"
DESCRIPTION = "Calculate velocity gradient, vorticity, Cp, Mach number."
DEFAULTS = {
    "velocity_x": "velocity_x",
    "velocity_y": "velocity_y",
    "velocity_z": "velocity_z",
    "pressure": "pressure",
    "density": "density",
    "specific_heat_ratio": 1.4,
    "velocity_gradient_switch": True,
    "vorticity_switch": True,
    "pressure_coefficient_switch": False,
    "velocity_amplitude_switch": False,
    "sound_speed_switch": False,
    "mach_switch": False,
    "p_inf": 101325.0,
    "rho_inf": 1.225,
    "U_inf": 50.0,
}


def execute(post_data, params: dict, zone_name: str) -> dict:
    multiblock = post_data.get_vtk_data()
    output_dir = os.path.dirname(post_data.file_path)
    result_dir = os.path.join(output_dir, "VelocityGradient")
    os.makedirs(result_dir, exist_ok=True)

    n_blocks = multiblock.GetNumberOfBlocks()
    for i in range(n_blocks):
        block = multiblock.GetBlock(i)
        if block is None:
            continue
        result_block = _compute_single(block, params)
        multiblock.SetBlock(i, result_block)

    # Write result
    output_path = os.path.join(result_dir, "res.vtm")
    output_path = os.path.normpath(output_path).replace("\\", "/")
    writer = vtk.vtkXMLMultiBlockDataWriter()
    writer.SetFileName(output_path)
    writer.SetInputData(multiblock)
    writer.Write()

    return {
        "type": "file",
        "summary": f"Velocity gradient computed for {n_blocks} blocks, saved to {output_path}",
        "data": {"output_file": output_path},
        "output_files": [output_path],
    }


def _compute_single(point_set, params):
    vg = vtk.CalculateVelocityGradient()
    vg.SetInputData(point_set)
    vg.SetScalarThreeComponent(
        str(params["velocity_x"]),
        str(params["velocity_y"]),
        str(params["velocity_z"]),
    )
    vg.SetPressureName(str(params["pressure"]))
    vg.SetDensityName(str(params["density"]))
    vg.SetSpecificHeatRatio(float(params["specific_heat_ratio"]))
    vg.SetReferenceData(float(params["p_inf"]), float(params["rho_inf"]), float(params["U_inf"]))
    vg.SetCulVelocityGradient(bool(params["velocity_gradient_switch"]))
    vg.SetCulVorticity(bool(params["vorticity_switch"]))
    vg.SetCulPressureCoefficient(bool(params["pressure_coefficient_switch"]))
    vg.SetCulVelocityAmplitude(bool(params["velocity_amplitude_switch"]))
    vg.SetCulSoundSpeed(bool(params["sound_speed_switch"]))
    vg.SetCulMach(bool(params["mach_switch"]))
    vg.Updata()  # legacy API typo preserved
    return vg.getOutput()
```

**Step 4: Run tests, verify pass**

**Step 5: Commit**

```bash
git add post_service/algorithms/velocity_gradient.py tests/post_service/algorithms/test_velocity_gradient.py
git commit -m "feat(algorithms): add velocity_gradient plugin (VTK C++ wrapper)"
```

---

## Task 7: PostEngine 计算引擎

**Files:**
- Create: `post_service/engine.py`
- Test: `tests/post_service/test_engine.py`

**Step 1: Write failing tests**

```python
# tests/post_service/test_engine.py
import pytest
import os
from unittest.mock import MagicMock, patch
from post_service.engine import PostEngine


class TestPostEngine:
    def setup_method(self):
        self.engine = PostEngine(algorithms_dir=None)  # no real algorithms

    def test_list_files(self, tmp_path):
        (tmp_path / "a.cgns").touch()
        (tmp_path / "b.plt").touch()
        (tmp_path / "c.txt").touch()
        result = self.engine.list_files(str(tmp_path))
        assert len(result["files"]) == 3

    def test_list_files_with_suffix(self, tmp_path):
        (tmp_path / "a.cgns").touch()
        (tmp_path / "b.plt").touch()
        result = self.engine.list_files(str(tmp_path), suffix=".cgns")
        assert len(result["files"]) == 1
        assert result["files"][0].endswith(".cgns")

    def test_get_method_template_all(self):
        self.engine.registry.methods = {
            "test": {"name": "test", "description": "desc", "defaults": {"a": 1}},
        }
        result = self.engine.get_method_template()
        assert len(result["methods"]) == 1

    def test_get_method_template_specific(self):
        self.engine.registry.methods = {
            "test": {"name": "test", "description": "desc", "defaults": {"a": 1}},
        }
        result = self.engine.get_method_template("test")
        assert result["method"] == "test"
        assert "defaults" in result

    def test_calculate_no_session(self):
        result = self.engine.calculate("no_session", "statistics", {}, "")
        assert "error" in result

    def test_calculate_no_file(self):
        self.engine.session_mgr.create("s1")
        result = self.engine.calculate("s1", "statistics", {}, "")
        assert "error" in result
```

**Step 2: Run tests, verify fail**

**Step 3: Implement**

```python
# post_service/engine.py
import os
import vtk
from post_service.session import SessionManager
from post_service.post_data import PostData
from post_service.algorithm_registry import AlgorithmRegistry


class PostEngine:
    def __init__(self, algorithms_dir: str = None):
        self.session_mgr = SessionManager()
        self.registry = AlgorithmRegistry()
        if algorithms_dir:
            self.registry.scan_and_load(algorithms_dir)

    def load_file(self, session_id: str, file_path: str) -> dict:
        file_path = os.path.normpath(file_path).replace("\\", "/")
        if not os.path.exists(file_path):
            return {"error": f"File not found: {file_path}"}

        try:
            reader = vtk.vtkRomtekIODriver()
            reader.ReadFiles(file_path, "", False)
            multiblock = reader.getOutPut()
        except Exception as e:
            return {"error": f"Failed to read file: {e}"}

        post_data = PostData(multiblock, file_path)

        state = self.session_mgr.get(session_id)
        if state is None:
            state = self.session_mgr.create(session_id)
        state.post_data = post_data
        state.output_dir = os.path.dirname(file_path)

        return post_data.get_summary()

    def calculate(self, session_id: str, method: str, params: dict, zone_name: str) -> dict:
        state = self.session_mgr.get(session_id)
        if state is None:
            return {"error": "Session not found. Please load a file first."}
        if state.post_data is None:
            return {"error": "No file loaded. Please use loadFile first."}

        entry = self.registry.get(method)
        if entry is None:
            available = [m["name"] for m in self.registry.list_methods()]
            return {"error": f"Unknown method '{method}'. Available: {available}"}

        merged = {**entry["defaults"], **params}
        try:
            return entry["execute"](state.post_data, merged, zone_name or "")
        except Exception as e:
            return {"error": f"Calculation failed: {e}"}

    def compare(self, session_id: str, source_a: str, source_b: str, **kwargs) -> dict:
        # Phase 1: basic implementation
        state = self.session_mgr.get(session_id)
        if state is None or state.post_data is None:
            return {"error": "No file loaded."}
        # TODO: full compare implementation
        return {"error": "compare not yet implemented"}

    def export_data(self, session_id: str, zone: str, scalars: list,
                    format: str = "csv") -> dict:
        state = self.session_mgr.get(session_id)
        if state is None or state.post_data is None:
            return {"error": "No file loaded."}

        pd = state.post_data
        import csv
        import json as json_mod

        if format == "csv":
            points = pd.get_points(zone)
            output_path = os.path.join(state.output_dir, f"{zone}_export.csv")
            output_path = os.path.normpath(output_path).replace("\\", "/")
            with open(output_path, "w", newline="") as f:
                writer = csv.writer(f)
                header = ["x", "y", "z"] + scalars
                writer.writerow(header)
                scalar_arrays = {}
                for s in scalars:
                    try:
                        scalar_arrays[s] = pd.get_scalar(zone, s)
                    except ValueError:
                        return {"error": f"Scalar '{s}' not found in zone '{zone}'"}
                for i in range(len(points)):
                    row = list(points[i]) + [float(scalar_arrays[s][i]) for s in scalars]
                    writer.writerow(row)
            return {
                "type": "file",
                "summary": f"Exported {zone} ({len(scalars)} scalars, {len(points)} points) to {output_path}",
                "data": {"file_path": output_path, "format": format},
                "output_files": [output_path],
            }

        return {"error": f"Unsupported format: {format}"}

    def list_files(self, directory: str, suffix: str = None) -> dict:
        directory = os.path.normpath(directory).replace("\\", "/")
        if not os.path.isdir(directory):
            return {"error": f"Directory not found: {directory}"}
        files = []
        for f in sorted(os.listdir(directory)):
            full = os.path.join(directory, f)
            if not os.path.isfile(full):
                continue
            if suffix and not f.endswith(suffix):
                continue
            files.append(os.path.normpath(full).replace("\\", "/"))
        return {"files": files, "count": len(files), "directory": directory}

    def get_method_template(self, method: str = None) -> dict:
        if method:
            entry = self.registry.get(method)
            if entry is None:
                return {"error": f"Unknown method: {method}"}
            return {
                "method": entry["name"],
                "description": entry["description"],
                "defaults": entry["defaults"],
            }
        return {"methods": self.registry.list_methods()}

    # -- HTTP API methods (for frontend, large data) --

    def get_mesh_geometry(self, session_id: str, zone: str):
        state = self.session_mgr.get(session_id)
        if state is None or state.post_data is None:
            return None
        try:
            points = state.post_data.get_points(zone)
            return points.tobytes()
        except ValueError:
            return None

    def get_scalar_data(self, session_id: str, zone: str, name: str):
        state = self.session_mgr.get(session_id)
        if state is None or state.post_data is None:
            return None
        try:
            arr = state.post_data.get_scalar(zone, name)
            return arr.tobytes()
        except ValueError:
            return None
```

**Step 4: Run tests, verify pass**

**Step 5: Commit**

```bash
git add post_service/engine.py tests/post_service/test_engine.py
git commit -m "feat(post_service): add PostEngine core with load/calculate/export/list"
```

---

## Task 8: MCP 端点层（6 个 tool 薄壳）

**Files:**
- Create: `post_service/mcp_tools/__init__.py`
- Create: `post_service/mcp_tools/load_file.py`
- Create: `post_service/mcp_tools/calculate.py`
- Create: `post_service/mcp_tools/compare.py`
- Create: `post_service/mcp_tools/export_data.py`
- Create: `post_service/mcp_tools/list_files.py`
- Create: `post_service/mcp_tools/get_method_template.py`

**Step 1: Implement all 6 thin shells (no separate tests — these are just parameter pass-through)**

每个文件就是参数解析 → 调 engine → 返回。以 `load_file.py` 为例：

```python
# post_service/mcp_tools/load_file.py
def register(mcp, engine):
    @mcp.tool(description="Load a CFD data file and return its summary.")
    def loadFile(file_path: str, session_id: str = "default") -> dict:
        return engine.load_file(session_id, file_path)
```

```python
# post_service/mcp_tools/calculate.py
def register(mcp, engine):
    @mcp.tool(description="Run a calculation on the loaded file and return numerical results.")
    def calculate(method: str, params: str = "{}", zone_name: str = "",
                  session_id: str = "default") -> dict:
        import json
        parsed_params = json.loads(params) if isinstance(params, str) else params
        return engine.calculate(session_id, method, parsed_params, zone_name)
```

```python
# post_service/mcp_tools/compare.py
def register(mcp, engine):
    @mcp.tool(description="Compare data from two or more sources (zones, files, CSV).")
    def compare(source_a: str, source_b: str, session_id: str = "default") -> dict:
        return engine.compare(session_id, source_a, source_b)
```

```python
# post_service/mcp_tools/export_data.py
def register(mcp, engine):
    @mcp.tool(description="Export data to a file (CSV, VTM, image).")
    def exportData(zone: str, scalars: str = "[]", format: str = "csv",
                   session_id: str = "default") -> dict:
        import json
        scalar_list = json.loads(scalars) if isinstance(scalars, str) else scalars
        return engine.export_data(session_id, zone, scalar_list, format)
```

```python
# post_service/mcp_tools/list_files.py
def register(mcp, engine):
    @mcp.tool(description="List available files in a directory.")
    def listFiles(directory: str = ".", suffix: str = "") -> dict:
        return engine.list_files(directory, suffix or None)
```

```python
# post_service/mcp_tools/get_method_template.py
def register(mcp, engine):
    @mcp.tool(description="Show available methods or parameters for a specific method.")
    def getMethodTemplate(method: str = "") -> dict:
        return engine.get_method_template(method or None)
```

**Step 2: Commit**

```bash
git add post_service/mcp_tools/
git commit -m "feat(post_service): add 6 MCP tool thin shells"
```

---

## Task 9: HTTP API 端点层

**Files:**
- Create: `post_service/http_api/__init__.py`
- Create: `post_service/http_api/mesh.py`
- Create: `post_service/http_api/scalar.py`
- Create: `post_service/http_api/file.py`
- Create: `post_service/http_api/upload.py`

**Step 1: Implement**

```python
# post_service/http_api/mesh.py
from fastapi import APIRouter, Response

router = APIRouter()

def setup(router_instance, engine):
    @router_instance.get("/api/mesh/{session_id}/{zone}")
    async def get_mesh(session_id: str, zone: str):
        data = engine.get_mesh_geometry(session_id, zone)
        if data is None:
            return {"error": "Not found"}
        return Response(content=data, media_type="application/octet-stream")
```

```python
# post_service/http_api/scalar.py
from fastapi import APIRouter, Response

router = APIRouter()

def setup(router_instance, engine):
    @router_instance.get("/api/scalar/{session_id}/{zone}/{name}")
    async def get_scalar(session_id: str, zone: str, name: str):
        data = engine.get_scalar_data(session_id, zone, name)
        if data is None:
            return {"error": "Not found"}
        return Response(content=data, media_type="application/octet-stream")
```

```python
# post_service/http_api/file.py
from fastapi import APIRouter
from fastapi.responses import FileResponse
import os

router = APIRouter()

def setup(router_instance, engine):
    @router_instance.get("/api/file/{path:path}")
    async def download_file(path: str):
        path = os.path.normpath(path).replace("\\", "/")
        if not os.path.exists(path):
            return {"error": f"File not found: {path}"}
        return FileResponse(path)
```

```python
# post_service/http_api/upload.py
from fastapi import APIRouter, UploadFile, File
import os
import tempfile

router = APIRouter()

def setup(router_instance, engine):
    @router_instance.post("/api/upload")
    async def upload_file(file: UploadFile = File(...)):
        upload_dir = tempfile.mkdtemp(prefix="chatcfd_")
        file_path = os.path.join(upload_dir, file.filename)
        file_path = os.path.normpath(file_path).replace("\\", "/")
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
        return {"file_path": file_path, "size": len(content)}
```

**Step 2: Commit**

```bash
git add post_service/http_api/
git commit -m "feat(post_service): add HTTP API endpoints (mesh/scalar/file/upload)"
```

---

## Task 10: 后处理服务入口 server.py

**Files:**
- Create: `post_service/server.py`

**Step 1: Implement**

```python
# post_service/server.py
import os
from fastapi import FastAPI
from fastmcp import FastMCP

from post_service.engine import PostEngine
from post_service.mcp_tools import load_file, calculate, compare, export_data, list_files, get_method_template
from post_service.http_api import mesh, scalar, file, upload

# Initialize
algorithms_dir = os.path.join(os.path.dirname(__file__), "algorithms")
engine = PostEngine(algorithms_dir=algorithms_dir)

# FastAPI app
app = FastAPI(title="ChatCFD Post Service")

# MCP endpoint
mcp = FastMCP("ChatCFD Post Service")
load_file.register(mcp, engine)
calculate.register(mcp, engine)
compare.register(mcp, engine)
export_data.register(mcp, engine)
list_files.register(mcp, engine)
get_method_template.register(mcp, engine)

# Mount MCP SSE
app.mount("/mcp", mcp.sse_app())

# HTTP API endpoints
api_router = FastAPI()
mesh.setup(app, engine)
scalar.setup(app, engine)
file.setup(app, engine)
upload.setup(app, engine)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

**Step 2: Smoke test**

Run: `cd d:\Git\chatCFD && python -m post_service.server`
Expected: Server starts on port 8000, no errors

**Step 3: Commit**

```bash
git add post_service/server.py
git commit -m "feat(post_service): add server.py entry point (FastAPI + FastMCP)"
```

---

## Task 11: Agent MCP Client

**Files:**
- Create: `agent/__init__.py`
- Create: `agent/mcp_client.py`
- Test: `tests/agent/test_mcp_client.py`

**Step 1: Implement**

```python
# agent/mcp_client.py
import asyncio
import json
from mcp.client.sse import sse_client
from mcp import ClientSession


class MCPClient:
    def __init__(self, mcp_url: str = "http://127.0.0.1:8000/mcp/sse"):
        self.mcp_url = mcp_url
        self._tools_raw = []
        self._tool_names = set()

    def load_tools(self):
        """Synchronously load tools from MCP server at startup."""
        async def _load():
            async with sse_client(self.mcp_url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    self._tools_raw = []
                    self._tool_names = set()
                    for tool in result.tools:
                        self._tool_names.add(tool.name)
                        self._tools_raw.append({
                            "name": tool.name,
                            "description": tool.description or "",
                            "inputSchema": tool.inputSchema or {},
                        })
        try:
            asyncio.run(_load())
        except Exception as e:
            print(f"[MCP] Failed to load tools: {e}")

    def call_tool(self, name: str, arguments: dict) -> str:
        """Synchronously call an MCP tool."""
        async def _call():
            async with sse_client(self.mcp_url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(name, arguments)
                    return result.content[0].text if result.content else "{}"
        try:
            return asyncio.run(_call())
        except Exception as e:
            return json.dumps({"error": f"MCP call failed: {e}"})

    def get_tools_for_llm(self) -> list:
        """Convert MCP tools to OpenAI function-calling format."""
        return [{
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["inputSchema"],
            },
        } for t in self._tools_raw]

    def has_tool(self, name: str) -> bool:
        return name in self._tool_names
```

**Step 2: Commit**

```bash
git add agent/__init__.py agent/mcp_client.py
git commit -m "feat(agent): add MCPClient (SSE connection + tool loading)"
```

---

## Task 12: Agent Harness

**Files:**
- Create: `agent/harness.py`
- Test: `tests/agent/test_harness.py`

**Step 1: Write failing tests**

```python
# tests/agent/test_harness.py
import pytest
from agent.harness import Harness


class TestHarness:
    def setup_method(self):
        self.h = Harness(path_whitelist=["D:/data", "C:/projects"],
                         max_file_size_mb=50)

    def test_path_whitelist_pass(self):
        result = self.h.before_call("loadFile", {"file_path": "D:/data/test.cgns"})
        assert result is None  # allowed

    def test_path_whitelist_block(self):
        result = self.h.before_call("loadFile", {"file_path": "C:/Windows/system32/cmd.exe"})
        assert result is not None
        assert "error" in result

    def test_coding_confirm_block(self):
        result = self.h.before_call("run_bash", {"command": "python script.py"},
                                    user_confirmed_coding=False)
        assert "error" in result

    def test_coding_confirm_pass(self):
        result = self.h.before_call("run_bash", {"command": "python script.py"},
                                    user_confirmed_coding=True)
        assert result is None

    def test_dangerous_command(self):
        result = self.h.before_call("run_bash", {"command": "rm -rf /"},
                                    user_confirmed_coding=True)
        assert "error" in result

    def test_truncate_short(self):
        result = self.h.after_call("calculate", {"summary": "ok", "data": "short"})
        assert result["data"] == "short"

    def test_truncate_long(self):
        self.h.max_return_chars = 100
        long_data = "x" * 200
        result = self.h.after_call("calculate", {"summary": "ok", "data": long_data})
        assert len(str(result.get("data", ""))) < 200
```

**Step 2: Run tests, verify fail**

**Step 3: Implement**

```python
# agent/harness.py
import os
import json


class Harness:
    def __init__(self, path_whitelist: list = None, max_file_size_mb: int = 50,
                 max_return_chars: int = 5000):
        self.path_whitelist = [os.path.normpath(p).replace("\\", "/")
                               for p in (path_whitelist or [])]
        self.max_file_size_mb = max_file_size_mb
        self.max_return_chars = max_return_chars
        self.dangerous_commands = ["rm -rf /", "sudo", "shutdown", "reboot",
                                   "mkfs", "dd if=", ":(){:|:&};:"]

    def before_call(self, tool_name: str, args: dict,
                    user_confirmed_coding: bool = False):
        # Path whitelist (loadFile, exportData)
        file_path = args.get("file_path", "")
        if file_path and tool_name in ("loadFile", "exportData"):
            if not self._check_path(file_path):
                return {"error": f"Path not in whitelist: {file_path}"}

        # File size check
        if tool_name == "loadFile" and file_path and os.path.exists(file_path):
            size_mb = os.path.getsize(file_path) / (1024 * 1024)
            if size_mb > self.max_file_size_mb:
                return {"error": f"File too large: {size_mb:.0f}MB (limit: {self.max_file_size_mb}MB)"}

        # AI Coding confirmation
        if tool_name in ("run_bash", "runPythonString"):
            if not user_confirmed_coding:
                return {"error": "需要用户确认后才能执行自定义代码。请先询问用户。"}
            # Dangerous command check
            cmd = args.get("command", "")
            for dangerous in self.dangerous_commands:
                if dangerous in cmd:
                    return {"error": f"Dangerous command blocked: {dangerous}"}

        return None  # allowed

    def after_call(self, tool_name: str, result: dict) -> dict:
        if not isinstance(result, dict):
            return result
        serialized = json.dumps(result, ensure_ascii=False, default=str)
        if len(serialized) > self.max_return_chars:
            # Keep summary, truncate data
            truncated = {k: v for k, v in result.items() if k != "data"}
            truncated["data"] = "[truncated — data too large for LLM context]"
            return truncated
        return result

    def _check_path(self, file_path: str) -> bool:
        if not self.path_whitelist:
            return True  # no whitelist = allow all (local mode)
        normalized = os.path.normpath(file_path).replace("\\", "/")
        return any(normalized.startswith(wp) for wp in self.path_whitelist)
```

**Step 4: Run tests, verify pass**

**Step 5: Commit**

```bash
git add agent/harness.py tests/agent/test_harness.py
git commit -m "feat(agent): add Harness with path whitelist, coding confirm, truncation"
```

---

## Task 13: Agent Session + Skills + Insight Log

**Files:**
- Create: `agent/session.py`
- Create: `agent/skills.py`
- Create: `agent/insight_log.py`

**Step 1: Implement all three (small modules)**

```python
# agent/session.py
import time


class AgentSession:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.messages = []
        self.user_confirmed_coding = False
        self.created_at = time.time()
        self.last_active = time.time()

    def touch(self):
        self.last_active = time.time()


class SessionPool:
    def __init__(self):
        self._sessions = {}

    def get(self, session_id: str):
        s = self._sessions.get(session_id)
        if s:
            s.touch()
        return s

    def create(self, session_id: str) -> AgentSession:
        s = AgentSession(session_id)
        self._sessions[session_id] = s
        return s

    def get_or_create(self, session_id: str) -> AgentSession:
        return self.get(session_id) or self.create(session_id)

    def destroy(self, session_id: str):
        self._sessions.pop(session_id, None)
```

```python
# agent/skills.py
SYSTEM_PROMPT_TEMPLATE = """你是 ChatCFD 智能助手，专注 CFD 仿真数据分析。

## 工作流
用户提到文件名          → loadFile(file_path=...)
用户说"算力和力矩"      → calculate(method="force_moment")
用户说"算涡量/马赫数"   → calculate(method="velocity_gradient")
用户说"提取数据/导出"   → exportData(zone=..., scalars=...)
用户说"对比/比较"       → compare(source_a=..., source_b=...)
用户说"有哪些算法"      → getMethodTemplate()

## 规则
- loadFile 只需调一次，后续操作自动复用已加载的文件
- 不要用 run_bash 写 Python 脚本来做 calculate/exportData 能做的事
- 参数不确定时先问用户，不要猜默认值
- 回答简短直接，不要重复 tool 返回的完整 JSON
- 力的单位是 N，压力单位是 Pa，长度单位是 m
- 只使用系统提供给你的工具，不要编造不存在的工具或功能
"""


def build_system_prompt() -> str:
    return SYSTEM_PROMPT_TEMPLATE
```

```python
# agent/insight_log.py
import json
import os
import time


def log_query(log_dir: str, session_id: str, user_input: str,
              resolution: str, tools_called: list = None):
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "insight_log.jsonl")
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "session_id": session_id,
        "user_input": user_input,
        "resolution": resolution,
        "tools_called": tools_called or [],
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
```

**Step 2: Commit**

```bash
git add agent/session.py agent/skills.py agent/insight_log.py
git commit -m "feat(agent): add AgentSession, Skills prompt, InsightLog"
```

---

## Task 14: Agent Loop

**Files:**
- Create: `agent/agent_loop.py`

**Step 1: Implement**

```python
# agent/agent_loop.py
import json
import litellm
from agent.harness import Harness
from agent.mcp_client import MCPClient
from agent.session import AgentSession
from agent.skills import build_system_prompt


def run(session: AgentSession, mcp_client: MCPClient, harness: Harness,
        model: str = "qwen/qwen-plus", max_rounds: int = 10) -> str:
    """Core agent loop: LLM → tool_call → execute → feed back → repeat."""
    system_msg = {"role": "system", "content": build_system_prompt()}
    tools = mcp_client.get_tools_for_llm()
    tools_called = []

    for _ in range(max_rounds):
        response = litellm.completion(
            model=model,
            messages=[system_msg] + session.messages,
            tools=tools if tools else None,
            max_tokens=4096,
        )
        msg = response.choices[0].message
        session.messages.append(msg.model_dump(exclude_none=True))

        # No tool calls = final response
        if not msg.tool_calls:
            return msg.content or ""

        # Execute tool calls
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            tools_called.append(name)

            # Harness before check
            blocked = harness.before_call(
                name, args,
                user_confirmed_coding=session.user_confirmed_coding,
            )
            if blocked:
                result = json.dumps(blocked, ensure_ascii=False)
            elif mcp_client.has_tool(name):
                raw = mcp_client.call_tool(name, args)
                try:
                    parsed = json.loads(raw)
                    parsed = harness.after_call(name, parsed)
                    result = json.dumps(parsed, ensure_ascii=False)
                except json.JSONDecodeError:
                    result = raw
            else:
                result = json.dumps({"error": f"Unknown tool: {name}"})

            session.messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    return "Maximum rounds reached."
```

**Step 2: Commit**

```bash
git add agent/agent_loop.py
git commit -m "feat(agent): add core agent loop (LiteLLM + Harness + MCP dispatch)"
```

---

## Task 15: Agent 服务入口

**Files:**
- Create: `agent/main.py`

**Step 1: Implement**

```python
# agent/main.py
"""ChatCFD Agent Service — CLI mode for Phase 1 testing."""
import os
from dotenv import load_dotenv

from agent.mcp_client import MCPClient
from agent.harness import Harness
from agent.session import SessionPool
from agent import agent_loop, insight_log

load_dotenv(override=True)
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")

MODEL = os.environ.get("MODEL_ID", "qwen/qwen-plus")
MCP_URL = os.environ.get("MCP_URL", "http://127.0.0.1:8000/mcp/sse")
LOG_DIR = os.environ.get("LOG_DIR", ".chatcfd")


def main():
    # Initialize
    mcp = MCPClient(MCP_URL)
    mcp.load_tools()
    print(f"Loaded {len(mcp._tools_raw)} MCP tools: {list(mcp._tool_names)}")

    harness = Harness()  # no whitelist in local mode
    pool = SessionPool()
    session = pool.get_or_create("cli")

    print("ChatCFD Agent (type 'q' to quit)\n")

    while True:
        try:
            query = input("\033[36mchatcfd >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break

        session.messages.append({"role": "user", "content": query})

        reply = agent_loop.run(session, mcp, harness, model=MODEL)

        if reply:
            print(reply)

        insight_log.log_query(LOG_DIR, "cli", query,
                              resolution="tool_resolved",
                              tools_called=[])
        print()


if __name__ == "__main__":
    main()
```

**Step 2: Commit**

```bash
git add agent/main.py
git commit -m "feat(agent): add CLI entry point for Phase 1 testing"
```

---

## Task 16: 集成测试

**Files:**
- Create: `tests/test_integration.py`

**Step 1: Write integration test**

```python
# tests/test_integration.py
"""
Integration test: PostEngine → MCP Tools → full chain.
Requires VTK and a test data file.
Run manually: python -m pytest tests/test_integration.py -v -s
"""
import pytest
import os
from post_service.engine import PostEngine


@pytest.fixture
def engine():
    algorithms_dir = os.path.join(os.path.dirname(__file__), "..", "post_service", "algorithms")
    return PostEngine(algorithms_dir=algorithms_dir)


class TestIntegration:
    def test_list_files(self, engine, tmp_path):
        (tmp_path / "test.cgns").touch()
        result = engine.list_files(str(tmp_path))
        assert "files" in result
        assert result["count"] == 1

    def test_get_method_template(self, engine):
        result = engine.get_method_template()
        assert "methods" in result
        names = [m["name"] for m in result["methods"]]
        assert "statistics" in names

    def test_get_method_template_specific(self, engine):
        result = engine.get_method_template("statistics")
        assert result["method"] == "statistics"

    def test_calculate_no_session(self, engine):
        result = engine.calculate("nonexistent", "statistics", {}, "")
        assert "error" in result

    # Full chain test (requires real VTK data, skip if not available)
    # def test_load_and_calculate(self, engine):
    #     result = engine.load_file("test", "path/to/real/file.cgns")
    #     assert "zones" in result
    #     calc = engine.calculate("test", "statistics", {}, result["zones"][0]["name"])
    #     assert "summary" in calc
```

**Step 2: Run tests**

Run: `cd d:\Git\chatCFD && python -m pytest tests/ -v --ignore=tests/test_integration.py`
Expected: All unit tests pass

Run: `cd d:\Git\chatCFD && python -m pytest tests/test_integration.py -v`
Expected: Non-VTK tests pass, VTK tests skipped

**Step 3: Commit**

```bash
git add tests/
git commit -m "test: add integration tests for PostEngine"
```

**Step 4: Push to remote**

```bash
git push origin master
```

---

## Phase 1 完成情况（截至 2026-04-07）

### 已完成（Task 1-16 + 额外功能）

| Task | 内容 | 状态 |
|------|------|:----:|
| 1-3 | PostData + Session + AlgorithmRegistry | ✅ |
| 4-6 | statistics / force_moment / velocity_gradient | ✅ |
| 7 | PostEngine 计算引擎 | ✅ |
| 8 | MCP 端点层（6 tool 薄壳） | ✅ |
| 9 | HTTP API 端点层 | ✅ |
| 10 | server.py 入口 | ✅ |
| 11 | Agent MCP Client | ✅ |
| 12 | Agent Harness | ✅ |
| 13 | Agent Session + Skills + InsightLog | ✅ |
| 14 | Agent Loop | ✅ |
| 15 | Agent main.py | ✅ |
| 16 | 集成测试 | ✅ 88 tests |
| 额外 | slice 切片（VTK 标准 filter） | ✅ |
| 额外 | render 离屏渲染（PNG） | ✅ |
| 额外 | compare 区域对比 | ✅ |
| 额外 | 分析存档 .chatcfd/ | ✅ |
| 额外 | 流式输出（token streaming） | ✅ |
| 额外 | Sidebar 会话管理（Claude 风格） | ✅ |
| 额外 | 多会话隔离（conversation_id 全链路） | ✅ |
| 额外 | Settings 面板（运行时切换模型） | ✅ |
| 额外 | 交互式 3D 流场（VTP + VTK.js） | ✅ MeshBrowser + VtpBrowser |
| 额外 | streamline 流线（VTK 标准 vtkStreamTracer） | ✅ |
| 额外 | contour 等值面（VTK 标准 vtkContourFilter） | ✅ |
| 额外 | VTP 文件 3D 查看（切片/流线/等值面结果） | ✅ VtpBrowser + scalar picker |
| 额外 | 坐标系指示器（AxesActor + OrientationMarkerWidget） | ✅ |
| 额外 | MeshBrowser 动态刷新标量（/api/zones）| ✅ |
| 额外 | Artifact 列表（关闭查看器后显示历史）| ✅ |
| 额外 | 聊天文件路径可点击 | ✅ |
| 额外 | DataTable 全高度 | ✅ |

### 已修复的 bug

- VTK.js 云图着色 — 已修（scalar coloring + LUT）
- Sidebar 折叠/展开 — 已修（Claude 风格，hover 展开）
- Artifact 面板 Claude 风格 — 已修（默认隐藏，点击弹出，关闭显示列表）
- 自动滚动 — 已修（只在底部时跟随）
- 输入框被挤 — 已修（chat-wrapper + min-height:0）
- ReadFiles 参数错误 — 已修（传 list 不是 string）
- CORS — 已修（post_service 全局中间件）
- 文件路径 URL 编码 — 已修（D: 冒号问题）
- Settings 模型名前缀 — 已修（openai/ 不是 qwen/）
- .vtm 文件路由 — 已修（不用 VtpBrowser 加载）
- MeshBrowser 不自动渲染 — 已修（VtkViewer key 强制 remount）
- Archive MD5 慢 — 已修（改为 size+mtime fingerprint）

---

## Phase 1.5: 物理量映射表升级

**数据源**: `docs/20260331 多专业标准物理量映射表v5.xlsx`（15 个 Sheet，覆盖 10 个求解器）

### 背景

当前 `physical_mapping.json` 只有 8 条手填映射，无求解器区分。映射表包含 89 种标准物理量、10 个求解器独立映射，且有量纲换算、置信度、同名异义检测、值域范围辅助判断。

**核心风险**：同名变量 "p" 在不同求解器含义不同：
- OpenFOAM 不可压：运动压力 m²/s²（需 ×ρ 换算）
- OpenFOAM 可压：真实静压 Pa
- Fluent：表压 Pa（需 +101325）
- CFX：绝对静压 Pa

当前实现把所有 "p" 都映射为 "pressure"，OpenFOAM 不可压用户力系数会差 ~1000 倍。

### 方案 A（Phase 1.5，先做）

用脚本把 Excel 转成**分求解器的 JSON**，替换 `physical_mapping.json`。

**Task 17: Excel → JSON 转换脚本**

**Files:**
- Create: `scripts/convert_mapping_excel.py`
- Create: `post_service/config/solver_mappings/` 目录
- Modify: `post_service/config/physical_mapping.json` → 新格式

**新 JSON 格式:**
```json
{
  "standard_quantities": {
    "pressure": {"display_name": "静压", "unit": "Pa", "type": "scalar"},
    "pressure_kinematic": {"display_name": "运动压力", "unit": "m²/s²", "type": "scalar"},
    ...共89条
  },
  "solver_mappings": {
    "OpenFOAM_incompressible": {
      "p": {"physical_name": "pressure_kinematic", "conversion": "multiply_density", "confidence": "HIGH"},
      "U": {"physical_name": "velocity_vector", "confidence": "HIGH"},
      ...
    },
    "Fluent": {
      "pressure": {"physical_name": "pressure", "conversion": "add_operating_pressure", "confidence": "HIGH"},
      "x-velocity": {"physical_name": "velocity_x", "confidence": "HIGH"},
      ...
    },
    "CGNS": { ... },
    "Tecplot": { ... },
    ...共10个求解器
  },
  "value_ranges": {
    "pressure": {"min": -5000, "max": 300000, "unit": "Pa"},
    "pressure_kinematic": {"min": -500, "max": 5000, "unit": "m²/s²"},
    ...共30条
  },
  "ambiguous_names": {
    "p": [
      {"solver": "OpenFOAM_incompressible", "physical_name": "pressure_kinematic"},
      {"solver": "OpenFOAM_compressible", "physical_name": "pressure"},
      {"solver": "Fluent", "physical_name": "pressure"},
      {"solver": "CFX", "physical_name": "pressure"}
    ],
    ...共14条
  }
}
```

**Task 18: PostData 适配新映射格式**

**Files:**
- Modify: `post_service/post_data.py`

`_resolve_name()` 改为：
1. 如果已知求解器类型 → 用对应 solver_mappings 查找
2. 未知求解器 → 遍历所有 solver_mappings 匹配，取置信度最高的
3. 置信度 LOW → 结合 value_ranges 辅助判断
4. 仍不确定 → 在 summary 中标注"推断，请确认"

**Task 19: 求解器自动识别**

**Files:**
- Create: `post_service/solver_detector.py`

根据 Sheet 2（求解器识别规则）实现：
- 文件格式特征（CGNS → HDF5 根节点、PLT → 魔数）
- 变量名模式匹配（有 "nut" → 可能 OpenFOAM）
- 返回 `{"solver": "Fluent", "confidence": "HIGH"}` 或 `{"solver": "unknown"}`

### 方案 B（Phase 2，后做）

- 量纲换算自动执行（conversion 字段）
- LLM 辅助推断未知变量
- 用户确认后写入 user_mappings/ 复用
- Excel ↔ JSON 双向同步脚本

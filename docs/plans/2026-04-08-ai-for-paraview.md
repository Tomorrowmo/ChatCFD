# AI for ParaView — 实现方案（修订版）

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 ChatCFD 升级为"AI 替代 ParaView"——统一几何操作基础设施，补齐 clip，扩展更多操作。

**现状:** 已有 slice / contour / streamline / render 四个几何算法，都返回 `type: "file"`，缺少统一的 geometry 基础设施。

**Architecture:** 新增 `type: "geometry"` 返回类型 + session 内存储 VTK 对象 + geometry HTTP 端点。现有算法迁移到新类型，新增 clip 算法。

---

## Task 1: 基础设施 — geometry result 支持

**Files:**
- Modify: `post_service/session.py` — SessionState 加 `geometry_results`
- Modify: `post_service/engine.py` — calculate() 后自动存储 geometry 结果
- Create: `post_service/http_api/geometry.py` — GET /api/geometry/{session_id}/{result_id}
- Modify: `post_service/http_api/__init__.py` — 注册路由

## Task 2: 新增 clip 算法

**Files:**
- Create: `post_service/algorithms/clip.py`

## Task 3: 迁移现有算法到 geometry 类型

将 slice / contour / streamline / render 的返回从 `type: "file"` 改为 `type: "geometry"`，
加入 `_vtk_output` 供 engine 自动存入 session，加入 `result_id`。

**Files:**
- Modify: `post_service/algorithms/slice.py`
- Modify: `post_service/algorithms/contour.py`
- Modify: `post_service/algorithms/streamline.py`
- Modify: `post_service/algorithms/render.py`（保持 type: "image"，不变）

## 后续 Phase（本次不实施）

- Phase 3: threshold / probe_line / glyph / calculator / cell_to_point
- Phase 4: 链式操作 + AI Skill
- 前端 geometry Artifact 渲染

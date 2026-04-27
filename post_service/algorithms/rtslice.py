"""Axis-aligned slice extraction using Romtek SliceFilter (Romtek C++ engine).

Replaces the old vtkCutter-based slice.py (now _slice.py).
Supports X/Y/Z axis-aligned slicing with configurable number of planes.
"""
import os

import vtk

NAME = "slice"
DESCRIPTION = """沿 X/Y/Z 轴生成多个**等距**平行切片截面。需体网格 zone。

参数：
- direction: 0=X, 1=Y, 2=Z（也接受字符串 'x','y','z'）
- n_slices: 切片数量，默认 3
- start/end: 该轴方向的位置范围；不传则自动取 zone bbox 全范围
- scalar: 着色用标量；不传则自动选第一个可用标量
- output_images: 是否同时渲染每个切片为 PNG 并合成 GIF 动画。默认 True（仅当
  n_slices > 1 生效）。用户明确只要 VTP 时传 False 可跳过渲染。
- image_width / image_height: 渲染分辨率，默认 1280x720

关键限制（LLM 请严格遵守）：
- **只支持等距切片**。切 n_slices 个平面在 [start, end] 区间内等距分布。
- **没有 position / positions / individual_planes / save_images / image_format
  这类参数**——不要猜。要生成 GIF 用 output_images=True（默认已开）。
- 想切 x=2,5,10 三个**非等距**位置 → **调 3 次本工具**，每次
  start=end=目标位置, n_slices=1。例：slice(start=2, end=2, n_slices=1, direction=0)
- 想切 x=2 到 10 之间 3 个等距位置（2, 6, 10） → 一次调用：
  slice(start=2, end=10, n_slices=3, direction=0)

输出 .vtp 文件（可在前端 3D 场景叠加显示）+ 可选 PNG 序列 + GIF 动画。
不适用：任意斜切面（本算法只做轴对齐）。"""
DEFAULTS = {
    "scalar": None,      # scalar for coloring (None = auto-pick first available)
    "direction": 0,      # 0=X, 1=Y, 2=Z (also accepts 'x','y','z')
    "n_slices": 3,       # number of slice planes
    "start": None,       # start position along axis (None = auto from bounds)
    "end": None,         # end position along axis (None = auto from bounds)
    "output_images": True,   # render each plane to PNG + combine GIF (n_slices>1 only)
    "image_width": 1280,
    "image_height": 720,
}


def execute(post_data, params: dict, zone_name: str, **kwargs) -> dict:
    multiblock = post_data.get_vtk_data()

    # --- 1. Validate params ---
    _dir_map = {"x": 0, "y": 1, "z": 2}
    raw_dir = params.get("direction", 0)
    direction = _dir_map.get(str(raw_dir).lower(), raw_dir) if isinstance(raw_dir, str) else raw_dir
    direction = int(direction)
    if direction not in (0, 1, 2):
        return {"error": f"Invalid direction={direction}. Must be 0 (X), 1 (Y), or 2 (Z)."}

    zones = post_data.get_zones()
    if not zones:
        return {"error": "No zones in dataset."}

    ref_zone = zone_name if zone_name and zone_name in zones else zones[0]
    ref_block = post_data._get_block(ref_zone)

    # Scalar is optional — auto-pick first available if not specified
    scalar_name = params.get("scalar") or params.get("scalar_name")
    if not scalar_name:
        available = post_data.get_scalar_names(ref_zone)
        if available:
            scalar_name = available[0]
        else:
            return {"error": "No scalars found in dataset and no 'scalar' parameter provided."}

    try:
        resolved_scalar = post_data._resolve_name(ref_zone, scalar_name, ref_block)
    except ValueError as e:
        return {"error": str(e)}

    # --- 2. Determine prep flags from frame 0 ---
    has_point_data = ref_block.GetPointData().GetArray(resolved_scalar) is not None
    has_cell_data = ref_block.GetCellData().GetArray(resolved_scalar) is not None
    needs_c2p = not has_point_data and has_cell_data

    # Prepare frame 0
    multiblock = _prepare_multiblock(multiblock, zone_name, needs_c2p)

    # --- 3. Auto start/end from bounds ---
    bounds = _get_global_bounds(multiblock)
    axis_min = bounds[direction * 2]
    axis_max = bounds[direction * 2 + 1]

    start = params.get("start")
    end = params.get("end")
    if start is None:
        start = axis_min
    if end is None:
        end = axis_max
    start = float(start)
    end = float(end)

    print(f"[rtslice] bounds={bounds}, direction={direction}, start={start}, end={end}")

    # --- 4. Build RomtekPostDataSet (data bridge) ---
    sequence = kwargs.get("sequence")
    frame_count = kwargs.get("frame_count", 1)
    time_labels = kwargs.get("time_labels", ["0"])

    try:
        rpdspf = vtk.RomtekPostDataSetPerFile()
        if sequence and frame_count > 1:
            all_mbs = sequence.load_all_multiblocks()
            for raw_mb in all_mbs:
                prepared = _prepare_multiblock(raw_mb, zone_name, needs_c2p)
                rpdspf.AddOriginalFrame(prepared)
        else:
            rpdspf.AddOriginalFrame(multiblock)
        rpds = vtk.RomtekPostDataSet()
        rpds.AddFileData(rpdspf)
    except Exception as e:
        return {"error": f"Failed to build RomtekPostDataSet: {e}"}

    # --- 5. Configure and run filter ---
    n_slices = int(params.get("n_slices", 3))

    print(f"[rtslice] Running SliceFilter: n_slices={n_slices}, scalar={resolved_scalar}, dir={direction}, range=[{start}, {end}]")

    try:
        filt = vtk.SliceFilter()
        filt.SetInput(rpds)
        filt.SetSliceGeneNum(n_slices)
        filt.SetScalar(resolved_scalar)
        filt.SetSliceDir(direction)
        filt.SetStartEndPos(start, end)
        filt.Update()
        result_mb = filt.GetOutput()
    except Exception as e:
        return {"error": f"SliceFilter failed: {e}"}

    # --- 6. Extract per-frame outputs ---
    # SliceFilter returns n_slices blocks per frame; merge within each frame
    if result_mb is None or result_mb.GetNumberOfBlocks() == 0:
        return {
            "error": (
                f"Slice produced no data for scalar '{scalar_name}' "
                f"direction={'XYZ'[direction]} range [{start:.4g}, {end:.4g}]"
            )
        }

    frame_outputs = _extract_frames(result_mb, frame_count, blocks_per_frame=n_slices)

    if not frame_outputs or all(o is None for o in frame_outputs):
        return {
            "error": (
                f"Slice produced empty result for scalar '{scalar_name}'. "
                f"direction={'XYZ'[direction]} range [{start:.4g}, {end:.4g}]"
            )
        }

    # --- 7. Save as VTP ---
    dir_label = "XYZ"[direction]
    file_stem = os.path.splitext(os.path.basename(post_data.file_path))[0]
    output_dir = os.path.join(os.path.dirname(post_data.file_path), file_stem)
    slice_dir = os.path.join(output_dir, "Slice")
    os.makedirs(slice_dir, exist_ok=True)

    base_name = f"slice_{dir_label}_{start:.4g}_{end:.4g}_n{n_slices}"

    # Save merged VTP (all planes in one file — for 3D viewer)
    all_paths = _save_frames(
        frame_outputs, slice_dir, base_name, frame_count,
    )

    # Save individual plane VTPs (one per slice — for render/GIF workflow)
    individual_paths = []
    if n_slices > 1 and frame_count == 1:
        total_blocks = result_mb.GetNumberOfBlocks()
        for i in range(min(n_slices, total_blocks)):
            blk = result_mb.GetBlock(i)
            if blk is None or blk.GetNumberOfPoints() == 0:
                continue
            plane_path = os.path.normpath(
                os.path.join(slice_dir, f"{base_name}_plane{i:04d}.vtp")
            ).replace("\\", "/")
            writer = vtk.vtkXMLPolyDataWriter()
            writer.SetFileName(plane_path)
            writer.SetInputData(blk)
            writer.SetDataModeToBinary()
            writer.SetCompressorTypeToZLib()
            writer.Write()
            individual_paths.append(plane_path)

    first_output = next((o for o in frame_outputs if o is not None), None)
    n_points = first_output.GetNumberOfPoints() if first_output else 0
    n_cells = first_output.GetNumberOfCells() if first_output else 0

    # --- 8. Render images + GIF if requested ---
    output_images = params.get("output_images", False)
    gif_path = None
    image_paths = []

    if output_images and n_slices > 1 and frame_count == 1:
        total_blocks = result_mb.GetNumberOfBlocks()
        img_dir = os.path.join(slice_dir, "images")
        os.makedirs(img_dir, exist_ok=True)

        # Compute global scalar range for consistent coloring
        global_range = None
        if resolved_scalar:
            gmin, gmax = float("inf"), float("-inf")
            for i in range(total_blocks):
                blk = result_mb.GetBlock(i)
                if blk is None:
                    continue
                arr = blk.GetPointData().GetArray(resolved_scalar)
                if arr is None:
                    arr = blk.GetCellData().GetArray(resolved_scalar)
                if arr:
                    lo, hi = arr.GetRange()
                    gmin, gmax = min(gmin, lo), max(gmax, hi)
            if gmin < float("inf"):
                global_range = (gmin, gmax)

        img_w = int(params.get("image_width", 1280))
        img_h = int(params.get("image_height", 720))

        for i in range(min(n_slices, total_blocks)):
            blk = result_mb.GetBlock(i)
            if blk is None or blk.GetNumberOfPoints() == 0:
                continue
            png_path = os.path.normpath(
                os.path.join(img_dir, f"{base_name}_{i:04d}.png")
            ).replace("\\", "/")
            _render_plane(blk, resolved_scalar, global_range, img_w, img_h, png_path, direction)
            image_paths.append(png_path)

        # Combine into GIF using PIL
        if len(image_paths) > 1:
            try:
                from PIL import Image
                frames = [Image.open(p) for p in image_paths]
                gif_path = os.path.normpath(
                    os.path.join(slice_dir, f"{base_name}.gif")
                ).replace("\\", "/")
                frames[0].save(
                    gif_path, save_all=True, append_images=frames[1:],
                    duration=500, loop=0,
                )
                print(f"[rtslice] GIF saved: {gif_path} ({len(frames)} frames)")
            except Exception as e:
                print(f"[rtslice] GIF synthesis failed: {e}")
                gif_path = None

    # --- 9. Return ---
    result_id = f"slice_{id(first_output) % 100000:05d}"
    zone_label = zone_name or "all zones"
    frame_info = f" ({frame_count} frames)" if frame_count > 1 else ""

    all_output_files = list(all_paths)
    gif_info = ""
    if gif_path:
        all_output_files.append(gif_path)
        gif_info = f" GIF: {gif_path}"
    if image_paths:
        all_output_files.extend(image_paths)

    return {
        "type": "geometry",
        "summary": (
            f"Slice of {zone_label} along {dir_label}-axis: "
            f"{n_slices} planes in [{start:.4g}, {end:.4g}], "
            f"{n_points} points, {n_cells} cells{frame_info}. "
            f"Colored by {scalar_name}. Saved to {all_paths[0]}.{gif_info}"
        ),
        "data": {
            "result_id": result_id,
            "output_file": all_paths[0],
            "gif_file": gif_path,
            "image_files": image_paths,
            "individual_planes": individual_paths,
            "scalar": scalar_name,
            "direction": dir_label,
            "n_slices": n_slices,
            "range": [start, end],
            "n_points": n_points,
            "n_cells": n_cells,
            "frame_count": frame_count,
            "time_labels": time_labels,
            "output_files_by_frame": all_paths,
        },
        "output_files": all_output_files,
        "_vtk_output": first_output,
    }


def _prepare_multiblock(raw_mb, zone_name, needs_c2p):
    """Apply zone filtering and optional cell-to-point conversion."""
    mb = raw_mb
    if zone_name:
        target_block = None
        for i in range(mb.GetNumberOfBlocks()):
            meta = mb.GetMetaData(i)
            if meta and meta.Has(vtk.vtkCompositeDataSet.NAME()):
                if meta.Get(vtk.vtkCompositeDataSet.NAME()) == zone_name:
                    target_block = mb.GetBlock(i)
                    break
        if target_block is not None:
            filtered_mb = vtk.vtkMultiBlockDataSet()
            filtered_mb.SetNumberOfBlocks(1)
            filtered_mb.SetBlock(0, target_block)
            filtered_mb.GetMetaData(0).Set(vtk.vtkCompositeDataSet.NAME(), zone_name)
            mb = filtered_mb
    if needs_c2p:
        converted_mb = vtk.vtkMultiBlockDataSet()
        converted_mb.SetNumberOfBlocks(mb.GetNumberOfBlocks())
        for i in range(mb.GetNumberOfBlocks()):
            block = mb.GetBlock(i)
            if block is None:
                continue
            c2p = vtk.vtkCellDataToPointData()
            c2p.SetInputData(block)
            c2p.Update()
            converted_mb.SetBlock(i, c2p.GetOutput())
            src_meta = mb.GetMetaData(i)
            if src_meta and src_meta.Has(vtk.vtkCompositeDataSet.NAME()):
                converted_mb.GetMetaData(i).Set(
                    vtk.vtkCompositeDataSet.NAME(),
                    src_meta.Get(vtk.vtkCompositeDataSet.NAME()),
                )
        mb = converted_mb
    return mb


def _extract_frames(result_mb, frame_count, blocks_per_frame=1):
    """Extract per-frame polydata from filter output multiblock.

    SliceFilter: blocks_per_frame = n_slices (merge within each frame).
    """
    total_blocks = result_mb.GetNumberOfBlocks()
    outputs = []
    for f in range(frame_count):
        start = f * blocks_per_frame
        end = min(start + blocks_per_frame, total_blocks)
        if start >= total_blocks:
            outputs.append(None)
            continue
        if blocks_per_frame == 1:
            blk = result_mb.GetBlock(start)
            if blk and blk.GetNumberOfPoints() > 0:
                outputs.append(blk)
            else:
                outputs.append(None)
        else:
            append = vtk.vtkAppendPolyData()
            valid = 0
            for i in range(start, end):
                blk = result_mb.GetBlock(i)
                if blk and blk.GetNumberOfPoints() > 0:
                    append.AddInputData(blk)
                    valid += 1
            if valid > 0:
                append.Update()
                outputs.append(append.GetOutput())
            else:
                outputs.append(None)
    return outputs


def _save_frames(frame_outputs, out_dir, base_name, frame_count):
    """Save per-frame polydata as individual .vtp files. Returns list of paths."""
    paths = []
    for i, output in enumerate(frame_outputs):
        if frame_count > 1:
            fname = f"{base_name}_f{i:04d}.vtp"
        else:
            fname = f"{base_name}.vtp"
        path = os.path.normpath(os.path.join(out_dir, fname)).replace("\\", "/")
        if output is not None:
            writer = vtk.vtkXMLPolyDataWriter()
            writer.SetFileName(path)
            writer.SetInputData(output)
            writer.SetDataModeToBinary()
            writer.SetCompressorTypeToZLib()
            writer.Write()
        paths.append(path)
    return paths


def _get_global_bounds(multiblock):
    """Compute global bounding box across all blocks."""
    xmin = ymin = zmin = float("inf")
    xmax = ymax = zmax = float("-inf")
    for i in range(multiblock.GetNumberOfBlocks()):
        block = multiblock.GetBlock(i)
        if block is None or block.GetNumberOfPoints() == 0:
            continue
        b = block.GetBounds()
        xmin = min(xmin, b[0])
        xmax = max(xmax, b[1])
        ymin = min(ymin, b[2])
        ymax = max(ymax, b[3])
        zmin = min(zmin, b[4])
        zmax = max(zmax, b[5])
    if xmin == float("inf"):
        return (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    return (xmin, xmax, ymin, ymax, zmin, zmax)


def _render_plane(polydata, scalar_name, scalar_range, width, height, output_path,
                   slice_direction=0):
    """Render a single slice plane to PNG, camera perpendicular to the plane."""
    geo = vtk.vtkGeometryFilter()
    geo.SetInputData(polydata)
    geo.Update()
    pd = geo.GetOutput()

    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(pd)

    if scalar_name:
        arr = pd.GetPointData().GetArray(scalar_name)
        if arr is None:
            arr = pd.GetCellData().GetArray(scalar_name)
        if arr:
            if pd.GetPointData().GetArray(scalar_name):
                mapper.SetScalarModeToUsePointFieldData()
            else:
                mapper.SetScalarModeToCellData()
            mapper.SelectColorArray(scalar_name)
            mapper.SetScalarRange(scalar_range or arr.GetRange())
            mapper.ScalarVisibilityOn()

            lut = vtk.vtkLookupTable()
            lut.SetHueRange(0.667, 0.0)
            lut.SetNumberOfColors(256)
            lut.Build()
            mapper.SetLookupTable(lut)

    actor = vtk.vtkActor()
    actor.SetMapper(mapper)

    renderer = vtk.vtkRenderer()
    renderer.AddActor(actor)
    renderer.SetBackground(0.2, 0.2, 0.3)

    if scalar_name and mapper.GetScalarVisibility():
        bar = vtk.vtkScalarBarActor()
        bar.SetLookupTable(mapper.GetLookupTable())
        bar.SetTitle(scalar_name)
        bar.SetNumberOfLabels(5)
        renderer.AddActor2D(bar)

    rw = vtk.vtkRenderWindow()
    rw.SetOffScreenRendering(1)
    rw.SetSize(width, height)
    rw.AddRenderer(renderer)

    # Camera perpendicular to slice plane
    renderer.ResetCamera()
    camera = renderer.GetActiveCamera()
    fp = list(camera.GetFocalPoint())
    dist = camera.GetDistance()
    # Position camera along the slice axis, looking at the plane face-on
    pos = list(fp)
    if slice_direction == 0:    # X slices → look along X
        pos[0] = fp[0] + dist
        camera.SetViewUp(0, 0, 1)
    elif slice_direction == 1:  # Y slices → look along Y
        pos[1] = fp[1] + dist
        camera.SetViewUp(0, 0, 1)
    else:                       # Z slices → look along Z
        pos[2] = fp[2] + dist
        camera.SetViewUp(0, 1, 0)
    camera.SetPosition(pos)
    renderer.ResetCamera()
    camera.Zoom(1.2)

    rw.Render()

    w2i = vtk.vtkWindowToImageFilter()
    w2i.SetInput(rw)
    w2i.SetScale(1)
    w2i.SetInputBufferTypeToRGB()
    w2i.ReadFrontBufferOff()
    w2i.Update()

    writer = vtk.vtkPNGWriter()
    writer.SetFileName(output_path)
    writer.SetInputConnection(w2i.GetOutputPort())
    writer.Write()
    rw.Finalize()

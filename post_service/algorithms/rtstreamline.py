"""Streamline computation — hybrid engine.

Engine selection (via `engine` param):
- "auto" (default): steady → vtk (_streamline, smart seeding); transient → rt (Romtek C++)
- "rt": force Romtek VectorFlowLineFilter. Use this when user reports poor streamline
        quality from the default engine ("效果不好" / "streamlines look bad").
- "vtk": force vtkStreamTracer + smart seeding (steady only; errors on transient).
"""
import importlib.util
import math
import os

import vtk

NAME = "streamline"
DESCRIPTION = (
    "Compute streamlines from velocity field. Outputs a .vtp file for 3D viewing. "
    "Set engine='rt' to switch to the Romtek C++ engine if the default result looks bad."
)
DEFAULTS = {
    "velocity_x": "velocity_x",
    "velocity_y": "velocity_y",
    "velocity_z": "velocity_z",
    "color_scalar": None,       # additional scalar for coloring (None = use velocity_x)
    "n_lines": 100,             # number of streamlines (seed density)
    "seed_type": 0,             # 0 = line, 1 = sphere
    "seed_start": None,         # [x, y, z] seed start position (None = auto)
    "seed_end": None,           # [x, y, z] seed end position (None = auto)
    "step_ratio": 1.0,          # line step ratio
    "max_propagation": None,    # max propagation length (None = auto)
    "seed_strategy": "auto",    # "auto"|"line"|"plane"|"inlet" (steady/vtk mode)
    "integration_direction": "forward",  # "forward"|"backward"|"both" (steady/vtk mode)
    "tube_radius": None,        # tube radius for rendering (None = auto, steady/vtk mode)
    "tube_sides": 12,           # tube polygon sides (steady/vtk mode)
    "engine": "auto",           # "auto"|"rt"|"vtk" — switch to "rt" if default looks bad
}


def _load_streamline_module():
    """Load _streamline.py as internal module (skipped by registry due to _ prefix)."""
    module_path = os.path.join(os.path.dirname(__file__), "_streamline.py")
    spec = importlib.util.spec_from_file_location("_streamline", module_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def execute(post_data, params: dict, zone_name: str, **kwargs) -> dict:
    # --- Engine routing ---
    sequence = kwargs.get("sequence")
    frame_count = kwargs.get("frame_count", 1)
    is_transient = sequence is not None and frame_count > 1

    engine = str(params.get("engine", "auto")).lower()

    # Explicit override takes precedence
    if engine == "rt":
        return _execute_transient(post_data, params, zone_name, **kwargs)
    if engine == "vtk":
        if is_transient:
            return {"error": "engine='vtk' does not support transient data. Use engine='rt' or 'auto'."}
        return _execute_steady(post_data, params, zone_name)

    # Auto: steady → vtk (better quality), transient → rt (multi-frame support)
    if is_transient:
        return _execute_transient(post_data, params, zone_name, **kwargs)
    return _execute_steady(post_data, params, zone_name)


def _execute_steady(post_data, params: dict, zone_name: str) -> dict:
    """Steady mode: delegate to _streamline.py (vtkStreamTracer + smart seeding)."""
    mod = _load_streamline_module()

    # Map rtstreamline params → _streamline params
    mapped = dict(params)
    if "n_lines" in mapped and "n_seeds" not in mapped:
        mapped["n_seeds"] = mapped.pop("n_lines")
    if "max_propagation" in mapped and "max_length" not in mapped:
        mapped["max_length"] = mapped.pop("max_propagation")
    # Pass through seed_strategy, integration_direction, tube_radius, tube_sides as-is

    return mod.execute(post_data, mapped, zone_name)


def _execute_transient(post_data, params: dict, zone_name: str, **kwargs) -> dict:
    """Transient mode: Romtek VectorFlowLineFilter (C++ engine, multi-frame)."""
    multiblock = post_data.get_vtk_data()

    # --- 1. Resolve velocity component names ---
    zones = post_data.get_zones()
    if not zones:
        return {"error": "No zones in dataset."}

    ref_zone = zone_name if zone_name and zone_name in zones else zones[0]
    ref_block = post_data._get_block(ref_zone)

    vx_param = str(params.get("velocity_x", "velocity_x"))
    vy_param = str(params.get("velocity_y", "velocity_y"))
    vz_param = str(params.get("velocity_z", "velocity_z"))

    try:
        resolved_vx = post_data._resolve_name(ref_zone, vx_param, ref_block)
        resolved_vy = post_data._resolve_name(ref_zone, vy_param, ref_block)
        resolved_vz = post_data._resolve_name(ref_zone, vz_param, ref_block)
    except ValueError as e:
        return {"error": f"Velocity field not found: {e}"}

    # Resolve color scalar
    color_param = params.get("color_scalar")
    if color_param:
        try:
            resolved_color = post_data._resolve_name(ref_zone, color_param, ref_block)
        except ValueError as e:
            return {"error": f"Color scalar not found: {e}"}
    else:
        resolved_color = resolved_vx  # fallback to velocity_x

    # --- 2. Determine prep flags from frame 0 ---
    needs_c2p = False
    for sname in (resolved_vx, resolved_vy, resolved_vz, resolved_color):
        if ref_block.GetPointData().GetArray(sname) is None and \
           ref_block.GetCellData().GetArray(sname) is not None:
            needs_c2p = True
            break

    # Prepare frame 0
    multiblock = _prepare_multiblock(multiblock, zone_name, needs_c2p)

    # --- 3. Auto seed positions and propagation from bounds ---
    bounds = _get_global_bounds(multiblock)
    dx = bounds[1] - bounds[0]
    dy = bounds[3] - bounds[2]
    dz = bounds[5] - bounds[4]
    diagonal = math.sqrt(dx * dx + dy * dy + dz * dz)

    seed_start = params.get("seed_start") or params.get("point1")
    seed_end = params.get("seed_end") or params.get("point2")
    if seed_start is None:
        seed_start = [bounds[0], bounds[2], bounds[4]]
    if seed_end is None:
        seed_end = [bounds[1], bounds[3], bounds[5]]
    seed_start = [float(v) for v in seed_start]
    seed_end = [float(v) for v in seed_end]

    max_propagation = params.get("max_propagation")
    if max_propagation is None:
        max_propagation = max(diagonal * 2.0, 1.0)
    max_propagation = float(max_propagation)

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
    n_lines = int(params.get("n_lines") or params.get("n_seeds") or 100)
    _seed_type_map = {"line": 0, "sphere": 1, "point": 0, "grid": 0, "rake": 0}
    raw_seed = params.get("seed_type", 0)
    seed_type = _seed_type_map.get(str(raw_seed).lower(), 0) if isinstance(raw_seed, str) else int(raw_seed)
    step_ratio = float(params.get("step_ratio", 1.0))

    try:
        filt = vtk.VectorFlowLineFilter()
        filt.SetInput(rpds)
        filt.SetStreamerType(0)
        filt.SetVectorScalar(resolved_vx, resolved_vy, resolved_vz)
        filt.SetAdditionalScalar(resolved_color)
        filt.SetLineStepRatio(step_ratio)
        filt.SetLineSeedType(seed_type)
        filt.SetLineGeneNum(n_lines)
        filt.SetLineMaximumPropagation(max_propagation)
        filt.SetLineStartEndPos(seed_start, seed_end)
        filt.Update()
        result_mb = filt.GetOutput()
    except Exception as e:
        return {"error": f"VectorFlowLineFilter failed: {e}"}

    # --- 6. Extract per-frame outputs ---
    if result_mb is None or result_mb.GetNumberOfBlocks() == 0:
        return {
            "error": (
                "Streamline produced no data. "
                "Try adjusting seed_start/seed_end or increasing n_lines."
            )
        }

    frame_outputs = _extract_frames(result_mb, frame_count, blocks_per_frame=1)

    if not frame_outputs or all(o is None for o in frame_outputs):
        return {
            "error": (
                "Streamline produced empty result. "
                "Check velocity field names and seed positions."
            )
        }

    # --- 7. Save as VTP (per-frame) ---
    file_stem = os.path.splitext(os.path.basename(post_data.file_path))[0]
    output_dir = os.path.join(os.path.dirname(post_data.file_path), file_stem)
    sl_dir = os.path.join(output_dir, "Streamline")
    os.makedirs(sl_dir, exist_ok=True)

    seed_label = {0: "line", 1: "sphere"}.get(seed_type, "line")
    all_paths = _save_frames(
        frame_outputs, sl_dir,
        f"streamline_{seed_label}_n{n_lines}", frame_count,
    )

    first_output = next((o for o in frame_outputs if o is not None), None)
    n_points = first_output.GetNumberOfPoints() if first_output else 0
    n_cells = first_output.GetNumberOfCells() if first_output else 0

    # --- 8. Return ---
    result_id = f"streamline_{id(first_output) % 100000:05d}"
    zone_label = zone_name or "all zones"
    color_label = color_param or vx_param
    frame_info = f" ({frame_count} frames)" if frame_count > 1 else ""
    return {
        "type": "geometry",
        "summary": (
            f"Streamlines of {zone_label}: "
            f"{n_lines} seeds ({seed_label}), {n_points} points, {n_cells} cells{frame_info}. "
            f"Colored by {color_label}. Saved to {all_paths[0]}"
        ),
        "data": {
            "result_id": result_id,
            "output_file": all_paths[0],
            "n_lines": n_lines,
            "n_points": n_points,
            "n_cells": n_cells,
            "seed_type": seed_label,
            "color_scalar": color_label,
            "frame_count": frame_count,
            "time_labels": time_labels,
            "output_files_by_frame": all_paths,
        },
        "output_files": all_paths,
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
    """Extract per-frame polydata from filter output multiblock."""
    total_blocks = result_mb.GetNumberOfBlocks()
    outputs = []
    for f in range(frame_count):
        start = f * blocks_per_frame
        if start >= total_blocks:
            outputs.append(None)
            continue
        blk = result_mb.GetBlock(start)
        if blk and blk.GetNumberOfPoints() > 0:
            outputs.append(blk)
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

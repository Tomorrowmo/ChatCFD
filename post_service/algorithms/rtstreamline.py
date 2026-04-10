"""Streamline computation using Romtek VectorFlowLineFilter (Romtek C++ engine).

Replaces the old vtkStreamTracer-based streamline.py (now _streamline.py).
Uses line or sphere seed placement with configurable density and propagation.
"""
import math
import os

import vtk

NAME = "streamline"
DESCRIPTION = "Compute streamlines from velocity field. Outputs a .vtp file for 3D viewing."
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
}


def execute(post_data, params: dict, zone_name: str) -> dict:
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

    # --- 2. Zone filtering ---
    if zone_name:
        try:
            target_block = post_data._get_block(zone_name)
        except ValueError as e:
            return {"error": str(e)}
        filtered_mb = vtk.vtkMultiBlockDataSet()
        filtered_mb.SetNumberOfBlocks(1)
        filtered_mb.SetBlock(0, target_block)
        filtered_mb.GetMetaData(0).Set(
            vtk.vtkCompositeDataSet.NAME(), zone_name
        )
        multiblock = filtered_mb

    # --- 3. Cell data -> point data conversion if needed ---
    # Check all relevant scalars (velocity components + color scalar)
    needs_c2p = False
    for sname in (resolved_vx, resolved_vy, resolved_vz, resolved_color):
        if ref_block.GetPointData().GetArray(sname) is None and \
           ref_block.GetCellData().GetArray(sname) is not None:
            needs_c2p = True
            break

    if needs_c2p:
        converted_mb = vtk.vtkMultiBlockDataSet()
        converted_mb.SetNumberOfBlocks(multiblock.GetNumberOfBlocks())
        for i in range(multiblock.GetNumberOfBlocks()):
            block = multiblock.GetBlock(i)
            if block is None:
                continue
            c2p = vtk.vtkCellDataToPointData()
            c2p.SetInputData(block)
            c2p.Update()
            converted_mb.SetBlock(i, c2p.GetOutput())
            src_meta = multiblock.GetMetaData(i)
            if src_meta and src_meta.Has(vtk.vtkCompositeDataSet.NAME()):
                converted_mb.GetMetaData(i).Set(
                    vtk.vtkCompositeDataSet.NAME(),
                    src_meta.Get(vtk.vtkCompositeDataSet.NAME()),
                )
        multiblock = converted_mb

    # --- 4. Auto seed positions and propagation from bounds ---
    bounds = _get_global_bounds(multiblock)
    dx = bounds[1] - bounds[0]
    dy = bounds[3] - bounds[2]
    dz = bounds[5] - bounds[4]
    diagonal = math.sqrt(dx * dx + dy * dy + dz * dz)

    seed_start = params.get("seed_start")
    seed_end = params.get("seed_end")
    if seed_start is None:
        seed_start = [bounds[0], bounds[2], bounds[4]]
    if seed_end is None:
        seed_end = [bounds[1], bounds[3], bounds[5]]
    # Ensure list of floats
    seed_start = [float(v) for v in seed_start]
    seed_end = [float(v) for v in seed_end]

    max_propagation = params.get("max_propagation")
    if max_propagation is None:
        max_propagation = max(diagonal * 2.0, 1.0)
    max_propagation = float(max_propagation)

    # --- 5. Build RomtekPostDataSet (data bridge) ---
    try:
        rpdspf = vtk.RomtekPostDataSetPerFile()
        rpdspf.AddOriginalFrame(multiblock)
        rpds = vtk.RomtekPostDataSet()
        rpds.AddFileData(rpdspf)
    except Exception as e:
        return {"error": f"Failed to build RomtekPostDataSet: {e}"}

    # --- 6. Configure and run filter ---
    n_lines = int(params.get("n_lines", 100))
    seed_type = int(params.get("seed_type", 0))
    step_ratio = float(params.get("step_ratio", 1.0))

    try:
        filt = vtk.VectorFlowLineFilter()
        filt.SetInput(rpds)
        filt.SetStreamerType(0)  # explicitly set to streamline mode
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

    # --- 7. Extract output polydata (block 0 = frame 0) ---
    if result_mb is None or result_mb.GetNumberOfBlocks() == 0:
        return {
            "error": (
                "Streamline produced no data. "
                "Try adjusting seed_start/seed_end or increasing n_lines."
            )
        }

    output = result_mb.GetBlock(0)
    if output is None or output.GetNumberOfPoints() == 0:
        return {
            "error": (
                "Streamline produced empty result. "
                "Check velocity field names and seed positions."
            )
        }

    n_points = output.GetNumberOfPoints()
    n_cells = output.GetNumberOfCells()

    # --- 8. Save as VTP ---
    file_stem = os.path.splitext(os.path.basename(post_data.file_path))[0]
    output_dir = os.path.join(os.path.dirname(post_data.file_path), file_stem)
    sl_dir = os.path.join(output_dir, "Streamline")
    os.makedirs(sl_dir, exist_ok=True)

    seed_label = "line" if seed_type == 0 else "sphere"
    output_path = os.path.normpath(
        os.path.join(sl_dir, f"streamline_{seed_label}_n{n_lines}.vtp")
    ).replace("\\", "/")

    writer = vtk.vtkXMLPolyDataWriter()
    writer.SetFileName(output_path)
    writer.SetInputData(output)
    writer.SetDataModeToBinary()
    writer.SetCompressorTypeToZLib()
    writer.Write()

    # --- 9. Return ---
    result_id = f"streamline_{id(output) % 100000:05d}"
    zone_label = zone_name or "all zones"
    color_label = color_param or vx_param
    return {
        "type": "geometry",
        "summary": (
            f"Streamlines of {zone_label}: "
            f"{n_lines} seeds ({seed_label}), {n_points} points, {n_cells} cells. "
            f"Colored by {color_label}. Saved to {output_path}"
        ),
        "data": {
            "result_id": result_id,
            "output_file": output_path,
            "n_lines": n_lines,
            "n_points": n_points,
            "n_cells": n_cells,
            "seed_type": seed_label,
            "color_scalar": color_label,
        },
        "output_files": [output_path],
        "_vtk_output": output,
    }


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

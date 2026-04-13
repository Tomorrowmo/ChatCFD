"""Iso-surface extraction using RomtekContourPlaneFilter (Romtek C++ engine).

Replaces the old vtkContourFilter-based contour.py (now _contour.py).
Uses the Romtek C++ ContourPlaneFilter via vtk Python bindings directly.
"""
import os

import vtk

NAME = "contour"
DESCRIPTION = "Extract iso-surface (contour) at specified scalar value. Outputs a .vtp file for 3D viewing."
DEFAULTS = {
    "scalar": None,      # required: scalar name for iso-surface extraction
    "value": None,       # [min, max] range. None = auto full range
    "n_contours": 10,    # number of iso-surfaces
}


def execute(post_data, params: dict, zone_name: str, **kwargs) -> dict:
    multiblock = post_data.get_vtk_data()

    # --- 1. Validate scalar ---
    scalar_name = params.get("scalar")
    if not scalar_name:
        return {"error": "Parameter 'scalar' is required. E.g. scalar='Pressure'"}

    zones = post_data.get_zones()
    if not zones:
        return {"error": "No zones in dataset."}
    ref_zone = zone_name if zone_name and zone_name in zones else zones[0]
    ref_block = post_data._get_block(ref_zone)
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

    # --- 3. Compute global scalar range ---
    global_min, global_max = _get_global_range(multiblock, resolved_scalar)

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
    n_contours = int(params.get("n_contours", 10))
    value = params.get("value")

    if value is not None:
        if isinstance(value, (list, tuple)) and len(value) == 2:
            iso_min, iso_max = float(value[0]), float(value[1])
        else:
            v = float(value)
            iso_min, iso_max = v, v
    else:
        iso_min, iso_max = global_min, global_max

    try:
        filt = vtk.ContourPlaneFilter()
        filt.SetInput(rpds)
        filt.SetIsoGeneNum(n_contours)
        filt.SetIsoVar(resolved_scalar)
        filt.SetScalar(resolved_scalar)
        filt.SetIsoMinMax(iso_min, iso_max)
        filt.Update()
        result_mb = filt.GetOutput()
    except Exception as e:
        return {"error": f"ContourPlaneFilter failed: {e}"}

    # --- 6. Extract per-frame outputs ---
    if result_mb is None or result_mb.GetNumberOfBlocks() == 0:
        return {
            "error": (
                f"Contour produced no data for scalar '{scalar_name}' "
                f"in range [{iso_min:.4g}, {iso_max:.4g}]"
            )
        }

    # ContourPlaneFilter: 1 block per frame
    frame_outputs = _extract_frames(result_mb, frame_count, blocks_per_frame=1)

    if not frame_outputs or all(o is None for o in frame_outputs):
        return {
            "error": (
                f"Contour produced empty result for scalar '{scalar_name}'. "
                f"Range is [{global_min:.4g}, {global_max:.4g}]"
            )
        }

    # --- 7. Save as VTP (per-frame) ---
    file_stem = os.path.splitext(os.path.basename(post_data.file_path))[0]
    output_dir = os.path.join(os.path.dirname(post_data.file_path), file_stem)
    contour_dir = os.path.join(output_dir, "Contour")
    os.makedirs(contour_dir, exist_ok=True)

    value_str = f"{iso_min:.4g}_{iso_max:.4g}" if value else f"auto{n_contours}"
    all_paths = _save_frames(
        frame_outputs, contour_dir,
        f"contour_{scalar_name}_{value_str}", frame_count,
    )

    first_output = next((o for o in frame_outputs if o is not None), None)
    n_points = first_output.GetNumberOfPoints() if first_output else 0
    n_cells = first_output.GetNumberOfCells() if first_output else 0

    # --- 8. Return ---
    result_id = f"contour_{id(first_output) % 100000:05d}"
    zone_label = zone_name or "all zones"
    frame_info = f" ({frame_count} frames)" if frame_count > 1 else ""
    return {
        "type": "geometry",
        "summary": (
            f"Contour of {scalar_name} on {zone_label}: "
            f"{n_points} points, {n_cells} cells{frame_info}. "
            f"Range [{global_min:.4g}, {global_max:.4g}]. "
            f"Saved to {all_paths[0]}"
        ),
        "data": {
            "result_id": result_id,
            "output_file": all_paths[0],
            "scalar": scalar_name,
            "range": [global_min, global_max],
            "n_points": n_points,
            "n_cells": n_cells,
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
    """Extract per-frame polydata from filter output multiblock.

    For most filters: blocks_per_frame=1, output block i = frame i.
    Merges blocks within each frame via vtkAppendPolyData if blocks_per_frame > 1.
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


def _get_global_range(multiblock, scalar_name):
    """Compute global min/max of scalar across all blocks."""
    global_min = float("inf")
    global_max = float("-inf")
    for i in range(multiblock.GetNumberOfBlocks()):
        block = multiblock.GetBlock(i)
        if block is None:
            continue
        arr = block.GetPointData().GetArray(scalar_name)
        if arr is None:
            arr = block.GetCellData().GetArray(scalar_name)
        if arr is None:
            continue
        lo, hi = arr.GetRange()
        global_min = min(global_min, lo)
        global_max = max(global_max, hi)
    if global_min == float("inf"):
        return 0.0, 0.0
    return global_min, global_max

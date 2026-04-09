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


def execute(post_data, params: dict, zone_name: str) -> dict:
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

    # --- 2. Zone filtering ---
    # Romtek filter merges all blocks internally. If zone_name specified,
    # build a single-block multiblock containing only that zone.
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
    has_point_data = ref_block.GetPointData().GetArray(resolved_scalar) is not None
    has_cell_data = ref_block.GetCellData().GetArray(resolved_scalar) is not None
    if not has_point_data and has_cell_data:
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
            # Preserve metadata
            src_meta = multiblock.GetMetaData(i)
            if src_meta and src_meta.Has(vtk.vtkCompositeDataSet.NAME()):
                converted_mb.GetMetaData(i).Set(
                    vtk.vtkCompositeDataSet.NAME(),
                    src_meta.Get(vtk.vtkCompositeDataSet.NAME()),
                )
        multiblock = converted_mb

    # --- 4. Compute global scalar range ---
    global_min, global_max = _get_global_range(multiblock, resolved_scalar)

    # --- 5. Build RomtekPostDataSet (data bridge) ---
    try:
        rpdspf = vtk.RomtekPostDataSetPerFile()
        rpdspf.AddOriginalFrame(multiblock)
        rpds = vtk.RomtekPostDataSet()
        rpds.AddFileData(rpdspf)
    except Exception as e:
        return {"error": f"Failed to build RomtekPostDataSet: {e}"}

    # --- 6. Configure and run filter ---
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

    # --- 7. Extract output polydata (block 0 = frame 0) ---
    if result_mb is None or result_mb.GetNumberOfBlocks() == 0:
        return {
            "error": (
                f"Contour produced no data for scalar '{scalar_name}' "
                f"in range [{iso_min:.4g}, {iso_max:.4g}]"
            )
        }

    output = result_mb.GetBlock(0)
    if output is None or output.GetNumberOfPoints() == 0:
        return {
            "error": (
                f"Contour produced empty result for scalar '{scalar_name}'. "
                f"Range is [{global_min:.4g}, {global_max:.4g}]"
            )
        }

    n_points = output.GetNumberOfPoints()
    n_cells = output.GetNumberOfCells()

    # --- 8. Save as VTP ---
    output_dir = os.path.dirname(post_data.file_path)
    contour_dir = os.path.join(output_dir, "Contour")
    os.makedirs(contour_dir, exist_ok=True)

    value_str = f"{iso_min:.4g}_{iso_max:.4g}" if value else f"auto{n_contours}"
    output_path = os.path.normpath(
        os.path.join(contour_dir, f"contour_{scalar_name}_{value_str}.vtp")
    ).replace("\\", "/")

    writer = vtk.vtkXMLPolyDataWriter()
    writer.SetFileName(output_path)
    writer.SetInputData(output)
    writer.SetDataModeToBinary()
    writer.SetCompressorTypeToZLib()
    writer.Write()

    # --- 9. Return (same format as old contour) ---
    result_id = f"contour_{id(output) % 100000:05d}"
    zone_label = zone_name or "all zones"
    return {
        "type": "geometry",
        "summary": (
            f"Contour of {scalar_name} on {zone_label}: "
            f"{n_points} points, {n_cells} cells. "
            f"Range [{global_min:.4g}, {global_max:.4g}]. "
            f"Saved to {output_path}"
        ),
        "data": {
            "result_id": result_id,
            "output_file": output_path,
            "scalar": scalar_name,
            "range": [global_min, global_max],
            "n_points": n_points,
            "n_cells": n_cells,
        },
        "output_files": [output_path],
        "_vtk_output": output,
    }


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

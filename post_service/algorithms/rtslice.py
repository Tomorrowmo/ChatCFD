"""Axis-aligned slice extraction using Romtek SliceFilter (Romtek C++ engine).

Replaces the old vtkCutter-based slice.py (now _slice.py).
Supports X/Y/Z axis-aligned slicing with configurable number of planes.
"""
import os

import vtk

NAME = "slice"
DESCRIPTION = "Extract axis-aligned slice planes colored by a scalar. Outputs a .vtp file for 3D viewing."
DEFAULTS = {
    "scalar": None,      # required: scalar for coloring the slice
    "direction": 0,      # 0=X, 1=Y, 2=Z
    "n_slices": 3,       # number of slice planes
    "start": None,       # start position along axis (None = auto from bounds)
    "end": None,         # end position along axis (None = auto from bounds)
}


def execute(post_data, params: dict, zone_name: str) -> dict:
    multiblock = post_data.get_vtk_data()

    # --- 1. Validate params ---
    scalar_name = params.get("scalar")
    if not scalar_name:
        return {"error": "Parameter 'scalar' is required. E.g. scalar='Pressure'"}

    direction = int(params.get("direction", 0))
    if direction not in (0, 1, 2):
        return {"error": f"Invalid direction={direction}. Must be 0 (X), 1 (Y), or 2 (Z)."}

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
            src_meta = multiblock.GetMetaData(i)
            if src_meta and src_meta.Has(vtk.vtkCompositeDataSet.NAME()):
                converted_mb.GetMetaData(i).Set(
                    vtk.vtkCompositeDataSet.NAME(),
                    src_meta.Get(vtk.vtkCompositeDataSet.NAME()),
                )
        multiblock = converted_mb

    # --- 4. Auto start/end from bounds ---
    bounds = _get_global_bounds(multiblock)
    # direction 0=X -> bounds indices (0,1), 1=Y -> (2,3), 2=Z -> (4,5)
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
    print(f"[rtslice] multiblock blocks={multiblock.GetNumberOfBlocks()}, resolved_scalar={resolved_scalar}")
    for i in range(multiblock.GetNumberOfBlocks()):
        blk = multiblock.GetBlock(i)
        if blk:
            print(f"[rtslice]   block[{i}]: type={blk.GetClassName()}, points={blk.GetNumberOfPoints()}, cells={blk.GetNumberOfCells()}")

    # --- 5. Build RomtekPostDataSet (data bridge) ---
    try:
        rpdspf = vtk.RomtekPostDataSetPerFile()
        rpdspf.AddOriginalFrame(multiblock)
        rpds = vtk.RomtekPostDataSet()
        rpds.AddFileData(rpdspf)
    except Exception as e:
        return {"error": f"Failed to build RomtekPostDataSet: {e}"}

    # --- 6. Configure and run filter ---
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

    # --- 7. Merge all non-empty output blocks ---
    # SliceFilter returns one block per slice plane; merge them into one polydata.
    if result_mb is None or result_mb.GetNumberOfBlocks() == 0:
        return {
            "error": (
                f"Slice produced no data for scalar '{scalar_name}' "
                f"direction={'XYZ'[direction]} range [{start:.4g}, {end:.4g}]"
            )
        }

    append = vtk.vtkAppendPolyData()
    valid_count = 0
    for i in range(result_mb.GetNumberOfBlocks()):
        blk = result_mb.GetBlock(i)
        if blk and blk.GetNumberOfPoints() > 0:
            append.AddInputData(blk)
            valid_count += 1

    if valid_count == 0:
        return {
            "error": (
                f"Slice produced empty result for scalar '{scalar_name}'. "
                f"direction={'XYZ'[direction]} range [{start:.4g}, {end:.4g}]"
            )
        }

    append.Update()
    output = append.GetOutput()

    n_points = output.GetNumberOfPoints()
    n_cells = output.GetNumberOfCells()

    # --- 8. Save as VTP ---
    dir_label = "XYZ"[direction]
    file_stem = os.path.splitext(os.path.basename(post_data.file_path))[0]
    output_dir = os.path.join(os.path.dirname(post_data.file_path), file_stem)
    slice_dir = os.path.join(output_dir, "Slice")
    os.makedirs(slice_dir, exist_ok=True)

    output_path = os.path.normpath(
        os.path.join(
            slice_dir,
            f"slice_{dir_label}_{start:.4g}_{end:.4g}_n{n_slices}.vtp",
        )
    ).replace("\\", "/")

    writer = vtk.vtkXMLPolyDataWriter()
    writer.SetFileName(output_path)
    writer.SetInputData(output)
    writer.SetDataModeToBinary()
    writer.SetCompressorTypeToZLib()
    writer.Write()

    # --- 9. Return ---
    result_id = f"slice_{id(output) % 100000:05d}"
    zone_label = zone_name or "all zones"
    return {
        "type": "geometry",
        "summary": (
            f"Slice of {zone_label} along {dir_label}-axis: "
            f"{n_slices} planes in [{start:.4g}, {end:.4g}], "
            f"{n_points} points, {n_cells} cells. "
            f"Colored by {scalar_name}. Saved to {output_path}"
        ),
        "data": {
            "result_id": result_id,
            "output_file": output_path,
            "scalar": scalar_name,
            "direction": dir_label,
            "n_slices": n_slices,
            "range": [start, end],
            "n_points": n_points,
            "n_cells": n_cells,
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

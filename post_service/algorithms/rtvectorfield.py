"""Vector field visualization using Romtek VectorFieldFilter (Romtek C++ engine).

Generates a structured vector field (arrows/glyphs) on a uniform grid within a
specified bounding box. Each grid point carries velocity components and optional
scalar values for coloring.
"""
import math
import os

import vtk

NAME = "vector_field"
DESCRIPTION = "Generate vector field arrows on a uniform grid. Outputs a .vtp file for 3D viewing."
DEFAULTS = {
    "velocity_x": "velocity_x",
    "velocity_y": "velocity_y",
    "velocity_z": "velocity_z",
    "scalar": None,              # primary display scalar (None = use velocity_x)
    "additional_scalar": "",     # optional second scalar (empty = skip)
    "box_min": None,             # [x, y, z] min corner (None = auto from bounds)
    "box_max": None,             # [x, y, z] max corner (None = auto from bounds)
    "resolution": [32, 32, 32], # [nx, ny, nz] grid resolution
}


def execute(post_data, params: dict, zone_name: str) -> dict:
    multiblock = post_data.get_vtk_data()

    # --- 1. Resolve scalar names ---
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

    # Primary display scalar
    scalar_param = params.get("scalar")
    if scalar_param:
        try:
            resolved_scalar = post_data._resolve_name(ref_zone, scalar_param, ref_block)
        except ValueError as e:
            return {"error": f"Scalar not found: {e}"}
    else:
        resolved_scalar = resolved_vx  # fallback

    # Optional additional scalar
    additional_param = params.get("additional_scalar", "")
    resolved_additional = ""
    if additional_param:
        try:
            resolved_additional = post_data._resolve_name(ref_zone, additional_param, ref_block)
        except ValueError as e:
            return {"error": f"Additional scalar not found: {e}"}

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
    needs_c2p = False
    check_scalars = [resolved_vx, resolved_vy, resolved_vz, resolved_scalar]
    if resolved_additional:
        check_scalars.append(resolved_additional)
    for sname in check_scalars:
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

    # --- 4. Auto box range from bounds ---
    bounds = _get_global_bounds(multiblock)

    box_min = params.get("box_min")
    box_max = params.get("box_max")
    if box_min is None:
        box_min = [bounds[0], bounds[2], bounds[4]]
    if box_max is None:
        box_max = [bounds[1], bounds[3], bounds[5]]
    box_min = [float(v) for v in box_min]
    box_max = [float(v) for v in box_max]

    resolution = params.get("resolution", [32, 32, 32])
    nx, ny, nz = int(resolution[0]), int(resolution[1]), int(resolution[2])

    # --- 5. Build RomtekPostDataSet (data bridge) ---
    try:
        rpdspf = vtk.RomtekPostDataSetPerFile()
        rpdspf.AddOriginalFrame(multiblock)
        rpds = vtk.RomtekPostDataSet()
        rpds.AddFileData(rpdspf)
    except Exception as e:
        return {"error": f"Failed to build RomtekPostDataSet: {e}"}

    # --- 6. Configure and run filter ---
    try:
        filt = vtk.VectorFieldFilter()
        filt.SetInput(rpds)
        filt.SetBoxRange(box_min, box_max)
        filt.SetSizeXYZ(nx, ny, nz)
        filt.SetVectorScalar(resolved_vx, resolved_vy, resolved_vz)
        filt.SetAdditionalScalar(resolved_scalar, resolved_additional)
        filt.Update()
        result_mb = filt.GetOutput()
    except Exception as e:
        return {"error": f"VectorFieldFilter failed: {e}"}

    # --- 7. Extract output polydata (block 0 = frame 0) ---
    if result_mb is None or result_mb.GetNumberOfBlocks() == 0:
        return {"error": "Vector field produced no data. Check box range and velocity field."}

    output = result_mb.GetBlock(0)
    if output is None or output.GetNumberOfPoints() == 0:
        return {"error": "Vector field produced empty result. Check box range covers the domain."}

    n_points = output.GetNumberOfPoints()
    n_cells = output.GetNumberOfCells()

    # --- 8. Save as VTP ---
    file_stem = os.path.splitext(os.path.basename(post_data.file_path))[0]
    output_dir = os.path.join(os.path.dirname(post_data.file_path), file_stem)
    vf_dir = os.path.join(output_dir, "VectorField")
    os.makedirs(vf_dir, exist_ok=True)

    output_path = os.path.normpath(
        os.path.join(vf_dir, f"vectorfield_{nx}x{ny}x{nz}.vtp")
    ).replace("\\", "/")

    writer = vtk.vtkXMLPolyDataWriter()
    writer.SetFileName(output_path)
    writer.SetInputData(output)
    writer.SetDataModeToBinary()
    writer.SetCompressorTypeToZLib()
    writer.Write()

    # --- 9. Return ---
    result_id = f"vectorfield_{id(output) % 100000:05d}"
    zone_label = zone_name or "all zones"
    scalar_label = scalar_param or vx_param
    return {
        "type": "geometry",
        "summary": (
            f"Vector field of {zone_label}: "
            f"{nx}x{ny}x{nz} grid, {n_points} points. "
            f"Colored by {scalar_label}. Saved to {output_path}"
        ),
        "data": {
            "result_id": result_id,
            "output_file": output_path,
            "resolution": [nx, ny, nz],
            "box_min": box_min,
            "box_max": box_max,
            "scalar": scalar_label,
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

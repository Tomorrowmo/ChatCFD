"""Clip: cut away half of the dataset using a plane, keeping one side."""

import os

import vtk

NAME = "clip"
DESCRIPTION = "Clip the dataset by a plane, keeping geometry on one side."
DEFAULTS = {
    "origin": None,       # [x, y, z] — default: dataset center
    "normal": [1, 0, 0],  # plane normal; kept side = normal direction
    "inside_out": False,   # True = keep the other side
}


def execute(post_data, params: dict, zone_name: str) -> dict:
    multiblock = post_data.get_vtk_data()

    # Get target data
    if zone_name:
        target = _get_zone_block(multiblock, zone_name)
        if target is None:
            return {"error": f"Zone '{zone_name}' not found"}
    else:
        target = _merge_all_blocks(multiblock)

    # Default origin = bounding box center
    origin = params.get("origin")
    if origin is None:
        bounds = target.GetBounds()
        origin = [
            (bounds[0] + bounds[1]) / 2,
            (bounds[2] + bounds[3]) / 2,
            (bounds[4] + bounds[5]) / 2,
        ]

    normal = params.get("normal", [1, 0, 0])
    inside_out = params.get("inside_out", False)

    # Convert to surface for clipping
    geo = vtk.vtkGeometryFilter()
    geo.SetInputData(target)
    geo.Update()
    polydata = geo.GetOutput()

    # Build clip plane
    plane = vtk.vtkPlane()
    plane.SetOrigin(float(origin[0]), float(origin[1]), float(origin[2]))
    plane.SetNormal(float(normal[0]), float(normal[1]), float(normal[2]))

    clipper = vtk.vtkClipPolyData()
    clipper.SetInputData(polydata)
    clipper.SetClipFunction(plane)
    clipper.SetInsideOut(inside_out)
    clipper.Update()

    output = clipper.GetOutput()
    n_points = output.GetNumberOfPoints()
    n_cells = output.GetNumberOfCells()

    if n_points == 0:
        return {"error": "Clip produced no geometry. Try a different plane position or flip inside_out."}

    result_id = f"clip_{id(output) % 100000:05d}"

    # Save VTP
    output_dir = os.path.dirname(post_data.file_path)
    clip_dir = os.path.join(output_dir, "Clip")
    os.makedirs(clip_dir, exist_ok=True)

    normal_str = f"{normal[0]}_{normal[1]}_{normal[2]}"
    output_path = os.path.normpath(
        os.path.join(clip_dir, f"clip_n{normal_str}.vtp")
    ).replace("\\", "/")

    writer = vtk.vtkXMLPolyDataWriter()
    writer.SetFileName(output_path)
    writer.SetInputData(output)
    writer.SetDataModeToBinary()
    writer.SetCompressorTypeToZLib()
    writer.Write()

    side = "negative" if inside_out else "positive"
    zone_label = zone_name or "all zones"

    return {
        "type": "geometry",
        "summary": (
            f"Clip of {zone_label} ({side} side): "
            f"origin={origin}, normal={normal}, "
            f"{n_points} points, {n_cells} cells. Saved to {output_path}"
        ),
        "data": {
            "result_id": result_id,
            "output_file": output_path,
            "n_points": n_points,
            "n_cells": n_cells,
            "origin": origin,
            "normal": normal,
        },
        "output_files": [output_path],
        "_vtk_output": output,
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

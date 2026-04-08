import os
import vtk

NAME = "slice"
DESCRIPTION = "Extract a 2D slice from 3D data at a specified position and direction."
DEFAULTS = {
    "origin": None,       # [x, y, z] — required, point on the plane
    "normal": [1, 0, 0],  # plane normal direction, default X-axis
    "zone_name_filter": None,  # optional: only slice specific zone
}


def execute(post_data, params: dict, zone_name: str) -> dict:
    multiblock = post_data.get_vtk_data()

    origin = params.get("origin")
    if origin is None:
        # Default: center of bounding box
        if zone_name:
            bounds = post_data.get_bounds(zone_name)
        else:
            # Use first zone
            zones = post_data.get_zones()
            bounds = post_data.get_bounds(zones[0]) if zones else None
        if bounds:
            origin = [
                (bounds["xmin"] + bounds["xmax"]) / 2,
                (bounds["ymin"] + bounds["ymax"]) / 2,
                (bounds["zmin"] + bounds["zmax"]) / 2,
            ]
        else:
            return {"error": "Cannot determine origin. Please provide origin=[x,y,z]"}

    normal = params.get("normal", [1, 0, 0])

    # Create cutting plane
    plane = vtk.vtkPlane()
    plane.SetOrigin(float(origin[0]), float(origin[1]), float(origin[2]))
    plane.SetNormal(float(normal[0]), float(normal[1]), float(normal[2]))

    # Get target data
    if zone_name:
        # Find specific zone block
        target = None
        for i in range(multiblock.GetNumberOfBlocks()):
            meta = multiblock.GetMetaData(i)
            if meta and meta.Get(vtk.vtkCompositeDataSet.NAME()) == zone_name:
                target = multiblock.GetBlock(i)
                break
        if target is None:
            return {"error": f"Zone '{zone_name}' not found"}
    else:
        # Merge all blocks
        append = vtk.vtkAppendFilter()
        for i in range(multiblock.GetNumberOfBlocks()):
            block = multiblock.GetBlock(i)
            if block:
                append.AddInputData(block)
        append.Update()
        target = append.GetOutput()

    # Cut
    cutter = vtk.vtkCutter()
    cutter.SetCutFunction(plane)
    cutter.SetInputData(target)
    cutter.Update()

    output = cutter.GetOutput()
    n_points = output.GetNumberOfPoints()
    n_cells = output.GetNumberOfCells()

    if n_points == 0:
        return {"error": "Slice produced no data. Check origin and normal parameters."}

    # Save as VTP
    output_dir = os.path.dirname(post_data.file_path)
    slice_dir = os.path.join(output_dir, "Slice")
    os.makedirs(slice_dir, exist_ok=True)

    normal_str = f"{normal[0]}_{normal[1]}_{normal[2]}"
    origin_str = f"{origin[0]:.4g}_{origin[1]:.4g}_{origin[2]:.4g}"
    output_path = os.path.join(slice_dir, f"slice_n{normal_str}_o{origin_str}.vtp")
    output_path = os.path.normpath(output_path).replace("\\", "/")

    writer = vtk.vtkXMLPolyDataWriter()
    writer.SetFileName(output_path)
    writer.SetInputData(output)
    writer.SetDataModeToBinary()
    writer.SetCompressorTypeToZLib()
    writer.Write()

    result_id = f"slice_{id(output) % 100000:05d}"
    zone_label = zone_name or "all zones"
    return {
        "type": "geometry",
        "summary": f"Slice of {zone_label}: origin={origin}, normal={normal}, {n_points} points, {n_cells} cells. Saved to {output_path}",
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

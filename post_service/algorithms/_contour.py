"""Iso-surface / contour extraction using vtkContourFilter (standard VTK)."""
import os
import vtk

NAME = "contour"
DESCRIPTION = "Extract iso-surface (contour) at specified scalar value. Outputs a .vtp file for 3D viewing."
DEFAULTS = {
    "scalar": None,      # required: scalar name to contour
    "value": None,       # required: iso-value (or list of values)
    "n_contours": 1,     # number of contours if value is not specified
}


def execute(post_data, params: dict, zone_name: str) -> dict:
    multiblock = post_data.get_vtk_data()

    # Get target block
    if zone_name:
        target = _get_zone_block(multiblock, zone_name)
        if target is None:
            return {"error": f"Zone '{zone_name}' not found"}
    else:
        target = _merge_all_blocks(multiblock)

    scalar_name = params.get("scalar")
    if not scalar_name:
        return {"error": "Parameter 'scalar' is required. E.g. scalar='Pressure'"}

    # Check scalar exists
    arr = target.GetPointData().GetArray(scalar_name)
    use_cell_data = False
    if arr is None:
        arr = target.GetCellData().GetArray(scalar_name)
        use_cell_data = True
    if arr is None:
        # Try physical name mapping
        try:
            resolved = post_data._resolve_name(
                zone_name or post_data.get_zones()[0],
                scalar_name,
                target,
            )
            arr = target.GetPointData().GetArray(resolved)
            if arr is None:
                arr = target.GetCellData().GetArray(resolved)
                use_cell_data = True
            scalar_name = resolved
        except ValueError:
            available = []
            pd = target.GetPointData()
            for i in range(pd.GetNumberOfArrays()):
                available.append(pd.GetArray(i).GetName())
            return {"error": f"Scalar '{scalar_name}' not found. Available: {available}"}

    scalar_range = arr.GetRange()

    # Set active scalar
    if use_cell_data:
        target.GetCellData().SetActiveScalars(scalar_name)
    else:
        target.GetPointData().SetActiveScalars(scalar_name)

    # Determine contour values
    values = params.get("value")
    n_contours = int(params.get("n_contours", 1))

    contour = vtk.vtkContourFilter()
    contour.SetInputData(target)

    if values is not None:
        # Single value or list of values
        if isinstance(values, (list, tuple)):
            for i, v in enumerate(values):
                contour.SetValue(i, float(v))
        else:
            contour.SetValue(0, float(values))
    else:
        # Auto-generate evenly spaced contours across range
        lo, hi = scalar_range
        contour.GenerateValues(n_contours, lo, hi)

    contour.Update()
    output = contour.GetOutput()

    n_points = output.GetNumberOfPoints()
    n_cells = output.GetNumberOfCells()

    if n_points == 0:
        return {"error": f"Contour produced no data for scalar '{scalar_name}' at specified value(s). Range is [{scalar_range[0]:.4g}, {scalar_range[1]:.4g}]"}

    # Save as VTP
    output_dir = os.path.dirname(post_data.file_path)
    contour_dir = os.path.join(output_dir, "Contour")
    os.makedirs(contour_dir, exist_ok=True)

    value_str = str(values).replace(" ", "") if values else f"auto{n_contours}"
    output_path = os.path.normpath(
        os.path.join(contour_dir, f"contour_{scalar_name}_{value_str}.vtp")
    ).replace("\\", "/")

    writer = vtk.vtkXMLPolyDataWriter()
    writer.SetFileName(output_path)
    writer.SetInputData(output)
    writer.SetDataModeToBinary()
    writer.SetCompressorTypeToZLib()
    writer.Write()

    result_id = f"contour_{id(output) % 100000:05d}"
    zone_label = zone_name or "all zones"
    return {
        "type": "geometry",
        "summary": f"Contour of {scalar_name} on {zone_label}: {n_points} points, {n_cells} cells. Range [{scalar_range[0]:.4g}, {scalar_range[1]:.4g}]. Saved to {output_path}",
        "data": {
            "result_id": result_id,
            "output_file": output_path,
            "scalar": scalar_name,
            "range": [scalar_range[0], scalar_range[1]],
            "n_points": n_points,
            "n_cells": n_cells,
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

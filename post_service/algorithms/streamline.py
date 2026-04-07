"""Streamline computation using vtkStreamTracer (standard VTK)."""
import os
import vtk

NAME = "streamline"
DESCRIPTION = "Compute streamlines from velocity field. Outputs a .vtp file for 3D viewing."
DEFAULTS = {
    "velocity_x": "velocity_x",
    "velocity_y": "velocity_y",
    "velocity_z": "velocity_z",
    "n_seeds": 50,                # number of seed points
    "seed_type": "line",          # "line" or "point"
    "seed_start": None,           # [x, y, z] — required for line seed
    "seed_end": None,             # [x, y, z] — required for line seed
    "max_length": 1000.0,         # max streamline length
    "integration_direction": "both",  # "forward", "backward", "both"
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

    # Build velocity vector field from 3 components
    vx_name = str(params.get("velocity_x", "velocity_x"))
    vy_name = str(params.get("velocity_y", "velocity_y"))
    vz_name = str(params.get("velocity_z", "velocity_z"))

    # Try to resolve names via PostData mapping
    try:
        vx_arr = post_data.get_scalar(zone_name or post_data.get_zones()[0], vx_name)
        vy_arr = post_data.get_scalar(zone_name or post_data.get_zones()[0], vy_name)
        vz_arr = post_data.get_scalar(zone_name or post_data.get_zones()[0], vz_name)
    except ValueError as e:
        return {"error": f"Velocity field not found: {e}"}

    # Add combined velocity vector to the dataset
    calc = vtk.vtkArrayCalculator()
    calc.SetInputData(target)
    calc.AddScalarArrayName(vx_name)
    calc.AddScalarArrayName(vy_name)
    calc.AddScalarArrayName(vz_name)
    calc.SetFunction(f"{vx_name}*iHat+{vy_name}*jHat+{vz_name}*kHat")
    calc.SetResultArrayName("Velocity_Vector")
    calc.Update()
    data_with_vel = calc.GetOutput()
    data_with_vel.GetPointData().SetActiveVectors("Velocity_Vector")

    # Create seed source
    n_seeds = int(params.get("n_seeds", 50))
    bounds = data_with_vel.GetBounds()

    seed_start = params.get("seed_start")
    seed_end = params.get("seed_end")
    if seed_start is None:
        seed_start = [bounds[0], (bounds[2] + bounds[3]) / 2, (bounds[4] + bounds[5]) / 2]
    if seed_end is None:
        seed_end = [bounds[1], (bounds[2] + bounds[3]) / 2, (bounds[4] + bounds[5]) / 2]

    seed_line = vtk.vtkLineSource()
    seed_line.SetPoint1(float(seed_start[0]), float(seed_start[1]), float(seed_start[2]))
    seed_line.SetPoint2(float(seed_end[0]), float(seed_end[1]), float(seed_end[2]))
    seed_line.SetResolution(n_seeds)
    seed_line.Update()

    # Stream tracer
    streamer = vtk.vtkStreamTracer()
    streamer.SetInputData(data_with_vel)
    streamer.SetSourceConnection(seed_line.GetOutputPort())
    streamer.SetMaximumPropagation(float(params.get("max_length", 1000.0)))
    streamer.SetIntegrationStepUnit(2)  # cell length
    streamer.SetInitialIntegrationStep(0.5)

    direction = str(params.get("integration_direction", "both")).lower()
    if direction == "forward":
        streamer.SetIntegrationDirectionToForward()
    elif direction == "backward":
        streamer.SetIntegrationDirectionToBackward()
    else:
        streamer.SetIntegrationDirectionToBoth()

    streamer.Update()
    output = streamer.GetOutput()

    n_lines = output.GetNumberOfLines() if hasattr(output, 'GetNumberOfLines') else output.GetNumberOfCells()
    n_points = output.GetNumberOfPoints()

    if n_points == 0:
        return {"error": "Streamline produced no data. Check velocity field and seed positions."}

    # Save as VTP
    output_dir = os.path.dirname(post_data.file_path)
    sl_dir = os.path.join(output_dir, "Streamline")
    os.makedirs(sl_dir, exist_ok=True)
    output_path = os.path.normpath(os.path.join(sl_dir, "streamlines.vtp")).replace("\\", "/")

    writer = vtk.vtkXMLPolyDataWriter()
    writer.SetFileName(output_path)
    writer.SetInputData(output)
    writer.Write()

    zone_label = zone_name or "all zones"
    return {
        "type": "file",
        "summary": f"Streamlines of {zone_label}: {n_lines} lines, {n_points} points. Saved to {output_path}",
        "data": {
            "output_file": output_path,
            "n_lines": n_lines,
            "n_points": n_points,
        },
        "output_files": [output_path],
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

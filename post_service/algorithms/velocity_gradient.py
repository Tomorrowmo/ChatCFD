"""Velocity gradient and derived quantities using VTK C++ CalculateVelocityGradient filter."""

import os

import vtk

NAME = "velocity_gradient"
DESCRIPTION = "Compute velocity gradient, vorticity, Cp, Mach, and sound speed on volume data."
DEFAULTS = {
    "velocity_x": "velocity_x",
    "velocity_y": "velocity_y",
    "velocity_z": "velocity_z",
    "pressure": "pressure",
    "density": "density",
    "specific_heat_ratio": 1.4,
    # Calculation switches
    "velocity_gradient_switch": True,
    "vorticity_switch": True,
    "pressure_coefficient_switch": False,
    "velocity_amplitude_switch": False,
    "sound_speed_switch": False,
    "mach_switch": False,
    # Reference conditions
    "p_inf": 101325.0,
    "rho_inf": 1.225,
    "U_inf": 50.0,
}

# Result array names (fixed, not user-configurable)
_RESULT_VELOCITY_GRADIENT = "VelocityGradient"
_RESULT_VORTICITY = "Vorticity"
_RESULT_CP = "PressureCoefficient"
_RESULT_VELOCITY = "Velocity"
_RESULT_SOUND_SPEED = "SoundSpeed"
_RESULT_MACH_NUMBER = "MachNumber"


def _compute_single(point_set, params: dict):
    """Run CalculateVelocityGradient on a single block. Returns the output vtkDataSet."""
    calc = vtk.CalculateVelocityGradient()
    calc.SetInputData(point_set)

    # Velocity components
    calc.SetScalarThreeComponent(
        params.get("velocity_x", "velocity_x"),
        params.get("velocity_y", "velocity_y"),
        params.get("velocity_z", "velocity_z"),
    )
    calc.SetPressureName(params.get("pressure", "pressure"))
    calc.SetDensityName(params.get("density", "density"))
    calc.SetSpecificHeatRatio(params.get("specific_heat_ratio", 1.4))

    # Result names
    calc.SetResultVelocityGradientName(_RESULT_VELOCITY_GRADIENT)
    calc.SetResultVorticityName(_RESULT_VORTICITY)
    calc.SetResultCpName(_RESULT_CP)
    calc.SetResultVelocityName(_RESULT_VELOCITY)
    calc.SetResultSoundSpeedName(_RESULT_SOUND_SPEED)
    calc.SetResultMachNumber(_RESULT_MACH_NUMBER)

    # Reference data
    calc.SetReferenceData(
        params.get("p_inf", 101325.0),
        params.get("rho_inf", 1.225),
        params.get("U_inf", 50.0),
    )

    # Calculation switches
    calc.SetCulVelocityGradient(params.get("velocity_gradient_switch", True))
    calc.SetCulVorticity(params.get("vorticity_switch", True))
    calc.SetCulPressureCoefficient(params.get("pressure_coefficient_switch", False))
    calc.SetCulVelocityAmplitude(params.get("velocity_amplitude_switch", False))
    calc.SetCulSoundSpeed(params.get("sound_speed_switch", False))
    calc.SetCulMach(params.get("mach_switch", False))

    # Note: legacy API uses "Updata" (typo preserved from C++ module)
    calc.Updata()
    return calc.getOutput()


def execute(post_data, params: dict, zone_name: str) -> dict:
    multiblock = post_data.get_vtk_data()
    n = multiblock.GetNumberOfBlocks()

    if n == 0:
        return {"error": "No blocks found in multiblock dataset."}

    # Process each block in-place on a shallow copy
    result_mb = vtk.vtkMultiBlockDataSet()
    result_mb.SetNumberOfBlocks(n)

    computed_names = []
    for i in range(n):
        block = multiblock.GetBlock(i)
        if block is None:
            result_mb.SetBlock(i, None)
            continue

        # Preserve block metadata (zone name)
        meta = multiblock.GetMetaData(i)
        if meta is not None and meta.Has(vtk.vtkCompositeDataSet.NAME()):
            block_name = meta.Get(vtk.vtkCompositeDataSet.NAME())
            result_mb.GetMetaData(i).Set(vtk.vtkCompositeDataSet.NAME(), block_name)
        else:
            block_name = f"Block_{i}"

        output = _compute_single(block, params)
        result_mb.SetBlock(i, output)
        computed_names.append(block_name)

    # Update the original multiblock in-place so session has new scalars
    for i in range(n):
        block = result_mb.GetBlock(i)
        if block is not None:
            multiblock.SetBlock(i, block)

    # Write output VTM file
    file_dir = os.path.dirname(post_data.file_path)
    out_dir = os.path.normpath(os.path.join(file_dir, "VelocityGradient")).replace("\\", "/")
    os.makedirs(out_dir, exist_ok=True)
    out_path = out_dir + "/res.vtm"

    writer = vtk.vtkXMLMultiBlockDataWriter()
    writer.SetFileName(out_path)
    writer.SetInputData(result_mb)
    writer.Write()

    # Build summary of what was computed
    active = []
    if params.get("velocity_gradient_switch", True):
        active.append("velocity_gradient")
    if params.get("vorticity_switch", True):
        active.append("vorticity")
    if params.get("pressure_coefficient_switch", False):
        active.append("Cp")
    if params.get("velocity_amplitude_switch", False):
        active.append("velocity_amplitude")
    if params.get("sound_speed_switch", False):
        active.append("sound_speed")
    if params.get("mach_switch", False):
        active.append("Mach")

    summary = (
        f"Computed {', '.join(active)} on {len(computed_names)} block(s). "
        f"Output: {out_path}"
    )

    # Return updated zones data so frontend shows MeshBrowser with new scalars
    # (PostData._zone_index now reflects the updated multiblock)
    post_data._build_zone_index()  # refresh zone index after in-place update
    zones_data = post_data.get_summary()

    return {
        "type": "numerical",
        "summary": summary,
        "data": zones_data,  # contains zones[] → frontend routes to MeshBrowser
        "output_files": [out_path],
    }
